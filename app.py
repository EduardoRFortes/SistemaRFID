from flask import Flask, request, jsonify, render_template, g, redirect, url_for, session
from flask_cors import CORS
from flask_socketio import SocketIO
import sqlite3
import os
import logging
from threading import Thread, Lock # Adicionado Lock
import paho.mqtt.client as mqtt
import json
import csv # Importado o módulo csv
from datetime import datetime # Importado para timestamp na inserção

app = Flask(__name__)
app.secret_key = 'segredo_super_secreto'  # importante para sessões
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

DB_FILE = "banco.db"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "/rfid/leituras"
LOG_CSV_FILE = "leituras_rfid_log.csv" # Nome do arquivo CSV para log
csv_file_lock = Lock() # Lock para garantir escrita segura em arquivo CSV

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("APP")

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE leituras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                epc TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                nome TEXT
            );
        """)
        cursor.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Banco de dados criado com sucesso.")

# Função para escrever no arquivo CSV
def write_to_csv(data):
    """
    Escreve um dicionário de dados em uma nova linha no arquivo CSV.
    Cria o cabeçalho se o arquivo não existir.
    """
    with csv_file_lock: # Garante que apenas uma thread escreva por vez
        file_exists = os.path.exists(LOG_CSV_FILE)
        with open(LOG_CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'epc', 'nome', 'mqttId']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader() # Escreve o cabeçalho apenas se o arquivo for novo

            writer.writerow(data)
            logger.info(f"Dados registrados em CSV: {data}")

# Middleware de login
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (username, password))
        user = cursor.fetchone()
        if user:
            session["usuario"] = username
            return redirect(url_for("homepage"))
        return render_template("login.html", erro="Usuário ou senha inválidos")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for("login"))

@app.route("/")
@login_required
def homepage():
    return render_template("index.html")

@app.route("/rfid", methods=["POST"])
def receber_rfid():
    data = request.get_json()
    # Adicionado "mqttId" na validação
    if not data or "epc" not in data or "timestamp" not in data or "mqttId" not in data:
        return jsonify({"erro": "JSON inválido ou incompleto"}), 400

    epc = data["epc"].strip().upper()
    timestamp = data["timestamp"].strip()
    mqttId = data["mqttId"].strip() # Este valor vem do JSON HTTP

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM leituras WHERE epc = ?;", (epc,))
    tag = cursor.fetchone()
    if tag is None:
        cursor.execute("INSERT INTO leituras (epc, timestamp) VALUES (?, ?)", (epc, timestamp))
        db.commit()
        nome = None
        logger.info(f"EPC inserido via HTTP: {epc}")
    else:
        nome = tag[3]
        logger.info(f"EPC já registrado via HTTP: {epc}")

    # Prepara os dados para o log CSV
    log_data = {
        'timestamp': timestamp,
        'epc': epc,
        'nome': nome if nome else "Desconhecido", # Garante que 'nome' não seja None para o CSV
        'mqttId': mqttId
    }
    write_to_csv(log_data) # Chama a função para escrever no CSV

    socketio.emit('novos_dados', {'nome': nome, 'epc': epc, 'timestamp': timestamp, 'mqttId': mqttId})
    return jsonify({"mensagem": "Salvo com sucesso"}), 200

@app.route("/definir", methods=["POST"])
def definir_nome():
    data = request.get_json()
    epc = data.get("epc", "").strip().upper()
    nome = data.get("nome", "").strip().title()

    if not epc or not nome:
        return jsonify({"erro": "Dados inválidos"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM leituras WHERE epc = ?", (epc,))
    resultado = cursor.fetchone()

    if resultado:
        cursor.execute("UPDATE leituras SET nome = ? WHERE epc = ?", (nome, epc))
    else:
        agora = datetime.now().isoformat()
        cursor.execute("INSERT INTO leituras (epc, nome, timestamp) VALUES (?, ?, ?)", (epc, nome, agora))

    db.commit()
    return jsonify({"mensagem": f"Nome definido para {epc}: {nome}"}), 200

@app.route("/dados", methods=["GET"])
def listar_dados():
    ordem = request.args.get("ordem", "desc").lower()
    epc_filtro = request.args.get("epc")

    db = get_db()
    cursor = db.cursor()

    query = "SELECT * FROM leituras"
    params = []

    if epc_filtro:
        query += " WHERE epc = ?"
        params.append(epc_filtro.strip().upper())

    query += f" ORDER BY id {'ASC' if ordem == 'asc' else 'DESC'}"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    dados = [{"id": row[0], "epc": row[1], "timestamp": row[2], "nome": row[3]} for row in rows]
    return jsonify(dados)

@socketio.on('connect')
def on_connect():
    logger.info("Cliente conectado via WebSocket.")

def iniciar_mqtt():
    def on_connect(client, userdata, flags, rc):
        logger.info(f"Conectado ao broker MQTT com código {rc}")
        client.subscribe(MQTT_TOPIC)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            epc = payload.get("epc", "").strip().upper()
            timestamp = payload.get("timestamp", "").strip()
            mqttId = payload.get("mqttId", "").strip() # Obtém o mqttId do payload MQTT

            # Incluído mqttId na validação aqui também
            if epc and timestamp and mqttId:
                db = sqlite3.connect(DB_FILE)
                cursor = db.cursor()

                cursor.execute("SELECT * FROM leituras WHERE epc = ?", (epc,))
                tag = cursor.fetchone()

                if tag is None:
                    cursor.execute("INSERT INTO leituras (epc, timestamp) VALUES (?, ?)", (epc, timestamp))
                    db.commit()
                    nome = None
                    logger.info(f"EPC inserido via MQTT: {epc}")
                else:
                    nome = tag[3]
                    logger.info(f"EPC já registrado via MQTT: {epc}")
                
                db.close()

                # Prepara os dados para o log CSV
                log_data = {
                    'timestamp': timestamp,
                    'epc': epc,
                    'nome': nome if nome else "Desconhecido", # Garante que 'nome' não seja None para o CSV
                    'mqttId': mqttId
                }
                write_to_csv(log_data) # Chama a função para escrever no CSV

                # CORREÇÃO: Usar 'mqttId' consistente com o front-end
                socketio.emit("novos_dados", {"epc": epc, "timestamp": timestamp, "nome": nome, "mqttId": mqttId})
            else:
                logger.warning(f"MQTT: JSON incompleto ou faltando mqttId. Payload: {payload}")
        except Exception as e:
            logger.error(f"Erro ao processar mensagem MQTT: {e}")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

if __name__ == "__main__":
    init_db()
    Thread(target=iniciar_mqtt).start()
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)