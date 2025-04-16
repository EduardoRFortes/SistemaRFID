from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__)
CORS(app)

DB_FILE = "banco.db"

# Inicializa banco de dados
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

@app.route("/")
def homepage():
    return render_template("index.html")

@app.route("/rfid", methods=["POST"])
def receber_rfid():
    data = request.get_json()
    if not data or "epc" not in data or "timestamp" not in data:
        return jsonify({"erro": "JSON inválido"}), 400

    epc = data["epc"]
    timestamp = data["timestamp"]

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if cursor.execute("SELECT * FROM leituras WHERE epc = ?;", (epc,)).fetchone() is None:
        cursor.execute("INSERT INTO leituras (epc, timestamp) VALUES (?, ?)", (epc, timestamp))
        conn.commit()
    conn.close()

    return jsonify({"mensagem": "Salvo com sucesso"}), 200


@app.route("/dados", methods=["GET"])
def listar_dados():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leituras ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    dados = [{"id": row[0], "epc": row[1], "timestamp": row[2], "nome": row[3]} for row in rows]
    return jsonify(dados)

@app.route("/atualizar_nome", methods=["POST"])
def atualizar_nome():
    data = request.get_json()
    epc = data.get("epc")
    nome = data.get("nome")
    if not epc or not nome:
        return jsonify({"erro": "Dados incompletos"}), 400

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE leituras SET nome = ? WHERE epc = ?", (nome, epc))
    conn.commit()
    conn.close()
    return jsonify({"mensagem": "Nome atualizado com sucesso"})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8000, debug = True)
