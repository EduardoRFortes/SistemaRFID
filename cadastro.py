import sqlite3

DB_FILE = "banco.db"

def criar_tabela():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Criando a tabela 'usuarios' caso não exista
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')
    
    conn.commit()
    conn.close()

def cadastrar_usuario(username, password):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO usuarios (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        print(f"Usuário '{username}' cadastrado com sucesso.")
    except sqlite3.IntegrityError:
        print(f"Usuário '{username}' já existe. Atualizando senha...")
        cursor.execute("UPDATE usuarios SET password = ? WHERE username = ?", (password, username))
        conn.commit()
        print(f"Senha de '{username}' atualizada com sucesso.")
    finally:
        conn.close()

if __name__ == "__main__":
    # Criando a tabela caso não exista
    criar_tabela()

    # Solicitando o nome de usuário e a senha
    usuario = input("Digite o nome de usuário: ").strip()
    senha = input("Digite a senha: ").strip()

    # Cadastrando o usuário
    cadastrar_usuario(usuario, senha)
