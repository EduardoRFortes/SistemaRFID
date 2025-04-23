from flask import Flask, request, jsonify, render_template, g
from flask_cors import CORS
from flask_socketio import SocketIO
import sqlite3
import os
import logging
from threading import Thread
import paho.mqtt.client as mqtt
import json

# Flask setup
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")  # Habilita CORS para WebSocket

# Configurações
DB_FILE = "banco.db"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "/rfid/leituras"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("APP")

# Banco de dados por request
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE)
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
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
        conn.commit()
        conn.close()
        logger.info("Banco de dados criado com sucesso.")

# Rota principal
@app.route("/")
def homepage():
    return render_template("index.html")

# Rota de recebimento HTTP
@app.route("/rfid", methods=["POST"])
def receber_rfid():
    data = request.get_json()
    if not data or "epc" not in data or "timestamp" not in data:
        return jsonify({"erro": "JSON inválido"}), 400

    epc = data["epc"].strip().upper()
    timestamp = data["timestamp"].strip()

    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM leituras WHERE epc = ?;", (epc,))
    tag = cursor.fetchone()
    if tag is None:
        cursor.execute("INSERT INTO leituras (epc, timestamp) VALUES (?, ?)", (epc, timestamp))
        db.commit()
        logger.info(f"EPC inserido via HTTP: {epc}")
        nome = None
    else:
        logger.info(f"EPC já registrado via HTTP: {epc}")
        nome = tag[3]

    socketio.emit('novos_dados', {'nome': nome, 'epc': epc, 'timestamp': timestamp})
    return jsonify({"mensagem": "Salvo com sucesso"}), 200

# Rota de associação de nome
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
        from datetime import datetime
        agora = datetime.now().isoformat()
        cursor.execute("INSERT INTO leituras (epc, nome, timestamp) VALUES (?, ?, ?)", (epc, nome, agora))

    db.commit()
    return jsonify({"mensagem": f"Nome definido para {epc}: {nome}"}), 200

# Rota para exibir dados
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

# WebSocket
@socketio.on('connect')
def on_connect():
    logger.info("Cliente conectado via WebSocket.")

# --- MQTT integrado ao app.py ---
def iniciar_mqtt():
    def on_connect(client, userdata, flags, rc):
        logger.info(f"Conectado ao broker MQTT com código {rc}")
        client.subscribe(MQTT_TOPIC)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            epc = payload.get("epc", "").strip().upper()
            timestamp = payload.get("timestamp", "").strip()

            if epc and timestamp:
                # Emitir para frontend
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

                socketio.emit("novos_dados", {"epc": epc, "timestamp": timestamp, "nome": nome})
            else:
                logger.warning("MQTT: JSON incompleto")
        except Exception as e:
            logger.error(f"Erro ao processar mensagem MQTT: {e}")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_forever()

# Inicialização
if __name__ == "__main__":
    init_db()
    Thread(target=iniciar_mqtt).start()  # Roda o MQTT em paralelo
    socketio.run(app, host="0.0.0.0", port=8000, debug=True)
