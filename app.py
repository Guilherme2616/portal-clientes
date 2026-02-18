from flask import send_from_directory
from flask import Flask, request, redirect, session, render_template
import psycopg2
import os
from dotenv import load_dotenv
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash, generate_password_hash
from flask import render_template, send_from_directory, session, abort


BASE_INFORMES = "storage/informes"

load_dotenv()

app = Flask(__name__)
app.secret_key = "chave_secreta_super_segura"
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_USERNAME")


mail = Mail(app)

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"),
        port=os.getenv("DB_PORT")
    )

@app.route("/")
def home():
    if "usuario_id" in session:
        return redirect("/documentos")
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        cpf = request.form["cpf"]
        cpf = cpf.replace(".", "").replace("-", "").replace("/", "")
        senha = request.form["senha"]

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, nome, cpf_cnpj, senha_hash FROM usuarios WHERE cpf_cnpj = %s", (cpf,))
        usuario = cur.fetchone()
        cur.close()
        conn.close()

        if usuario and check_password_hash(usuario[3], senha):
            session["usuario_id"] = usuario[0]
            session["usuario_nome"] = usuario[1]
            session["cpf"] = usuario[2]
            return redirect("/documentos")
        else:
            return "CPF ou senha inválidos"

    return render_template("login.html")
    


@app.route("/documentos")
def documentos():
    if "usuario_id" not in session:
        return redirect("/login")

    nome = session["usuario_nome"]
    return render_template("dashboard.html", nome=nome)

@app.route("/informes")
def informes():

    if not os.path.exists(BASE_INFORMES):
        return render_template("informes.html", anos=[])

    anos = sorted(os.listdir(BASE_INFORMES), reverse=True)

    return render_template("informes.html", anos=anos)

@app.route("/informes/visualizar/<ano>")
def visualizar_informe(ano):

    if "cpf" not in session:
        return redirect("/login")

    cpf = session.get("cpf")

    caminho_ano = os.path.join(BASE_INFORMES, ano)
    nome_arquivo = f"{cpf}.pdf"

    print("CPF:", cpf)
    print("Caminho:", caminho_ano)
    print("Arquivo:", nome_arquivo)

    if not os.path.exists(os.path.join(caminho_ano, nome_arquivo)):
        return render_template("informe_nao_encontrado.html")


    return send_from_directory(caminho_ano, nome_arquivo)

@app.route("/informes/baixar/<ano>")
def baixar_informe(ano):

    cpf = session.get("cpf")

    caminho_ano = os.path.join(BASE_INFORMES, ano)
    nome_arquivo = f"{cpf}.pdf"

    if not os.path.exists(os.path.join(caminho_ano, nome_arquivo)):
        abort(404)

    return send_from_directory(
        caminho_ano,
        nome_arquivo,
        as_attachment=True
    )


@app.route("/notas-fiscais")
def notas_fiscais():
    if "usuario_id" not in session:
        return redirect("/login")

    usuario_id = session["usuario_id"]

    base_dir = os.path.abspath(os.path.dirname(__file__))
    pasta_nf = os.path.join(base_dir, "documentos", str(usuario_id), "notas_fiscais")

    arquivos = []
    if os.path.exists(pasta_nf):
        arquivos = os.listdir(pasta_nf)

    return render_template("notas_fiscais.html", arquivos=arquivos)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/baixar/<tipo>/<nome_arquivo>")
def baixar(tipo, nome_arquivo):
    if "usuario_id" not in session:
        return redirect("/login")

    usuario_id = session["usuario_id"]

    base_dir = os.path.abspath(os.path.dirname(__file__))
    pasta_usuario = os.path.join(base_dir, "documentos", str(usuario_id), tipo)
    caminho_completo = os.path.join(pasta_usuario, nome_arquivo)

    if not os.path.exists(caminho_completo):
        return "Arquivo não encontrado", 404

    return send_from_directory(pasta_usuario, nome_arquivo, as_attachment=True)

@app.route("/admin/solicitacoes")
def admin_solicitacoes():
    if "admin_id" not in session:
        return redirect("/admin/login")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, nome_completo, cpf, email, status
        FROM solicitacoes_acesso
        WHERE status = 'pendente'
        ORDER BY id DESC
    """)

    solicitacoes = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("admin_solicitacoes.html", solicitacoes=solicitacoes)

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form["email"]
        senha = request.form["senha"]

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT id, senha_hash FROM admins WHERE email = %s", (email,))
        admin = cur.fetchone()

        cur.close()
        conn.close()

        if admin and check_password_hash(admin[1], senha):
            session["admin_id"] = admin[0]
            return redirect("/admin/solicitacoes")
        else:
            return render_template("admin_login.html", erro="Credenciais inválidas")

    return render_template("admin_login.html")


@app.route("/admin/aprovar/<int:id>")
def aprovar_solicitacao(id):
    if "admin_id" not in session:
        return redirect("/admin/login")

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT nome_completo, cpf, email, senha_hash
        FROM solicitacoes_acesso
        WHERE id = %s
    """, (id,))
    dados = cur.fetchone()

    if not dados:
        return "Solicitação não encontrada"

    nome, cpf, email, senha_hash = dados

    # Criar usuário
    cur.execute("""
        INSERT INTO usuarios (nome, cpf_cnpj, senha_hash)
        VALUES (%s, %s, %s)
    """, (nome, cpf, senha_hash))

    # Atualizar status
    cur.execute("""
        UPDATE solicitacoes_acesso
        SET status = 'aprovado'
        WHERE id = %s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    # ===== ENVIO DE EMAIL APROVAÇÃO =====
    try:
        msg = Message(
            subject="Acesso Aprovado - Portal do Cooperado",
            recipients=[email]
        )

        msg.body = f"""
Olá {nome},

Sua solicitação de acesso foi APROVADA.

Você já pode acessar o Portal do Cooperado utilizando seu CPF e senha cadastrados.

Atenciosamente,
Equipe Portal do Cooperado
"""

        mail.send(msg)

    except Exception as e:
        print("Erro ao enviar e-mail de aprovação:", e)

    return redirect("/admin/solicitacoes")


@app.route("/admin/rejeitar/<int:id>", methods=["POST"])
def rejeitar_solicitacao(id):
    if "admin_id" not in session:
        return redirect("/admin/login")

    motivo = request.form["motivo"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT nome_completo, email
        FROM solicitacoes_acesso
        WHERE id = %s
    """, (id,))
    dados = cur.fetchone()

    if not dados:
        return "Solicitação não encontrada"

    nome, email = dados

    cur.execute("""
        UPDATE solicitacoes_acesso
        SET status = 'rejeitado',
            motivo_rejeicao = %s
        WHERE id = %s
    """, (motivo, id))

    conn.commit()
    cur.close()
    conn.close()

    # ===== ENVIO DE EMAIL REJEIÇÃO =====
    try:
        msg = Message(
            subject="Solicitação Não Aprovada - Portal do Cooperado - Camda",
            recipients=[email]
        )

        msg.body = f"""
Olá {nome},

Sua solicitação de acesso não foi aprovada.

Motivo:
{motivo}

Caso tenha dúvidas, entre em contato com a equipe responsável.

Atenciosamente,
Cooperativa Camda
"""

        mail.send(msg)

    except Exception as e:
        print("Erro ao enviar e-mail de rejeição:", e)

    return redirect("/admin/solicitacoes")



@app.route("/primeiro-acesso", methods=["GET", "POST"])
def primeiro_acesso():
    if request.method == "POST":
        nome = request.form["nome"]
        cpf = request.form["cpf"]
        cpf = ''.join(filter(str.isdigit, cpf))
        email = request.form["email"]
        senha = request.form["senha"]

        conn = get_db_connection()
        cur = conn.cursor()

        # Validar se CPF existe na base
        cur.execute("SELECT 1 FROM clientes_base WHERE cpf = %s", (cpf,))
        cliente_existe = cur.fetchone()

        if not cliente_existe:
            cur.close()
            conn.close()
            return render_template("primeiro_acesso.html", erro="CPF não encontrado na base de clientes.")

        from werkzeug.security import generate_password_hash
        senha_hash = generate_password_hash(senha)

        # Inserir solicitação
        cur.execute("""
            INSERT INTO solicitacoes_acesso (nome_completo, cpf, email, senha_hash, status)
            VALUES (%s, %s, %s, %s, 'pendente')
        """, (nome, cpf, email, senha_hash))

        conn.commit()
        cur.close()
        conn.close()

        # ===== ENVIO DE EMAIL =====
        try:
            # Email para o setor responsável
            msg_admin = Message(
                subject="Nova Solicitação de Primeiro Acesso",
                recipients=["seuemail@empresa.com"]
            )

            msg_admin.body = f"""
Nova solicitação de acesso:

Nome: {nome}
CPF/CNPJ: {cpf}
E-mail: {email}

Acesse o sistema para analisar a solicitação.
"""

            mail.send(msg_admin)

            # Email de confirmação para o cliente
            msg_cliente = Message(
                subject="Recebemos sua solicitação - Portal do Cooperado",
                recipients=[email]
            )

            msg_cliente.body = f"""
Olá {nome},

Recebemos sua solicitação de primeiro acesso ao Portal do Cooperado.

Sua solicitação está em análise.
Você será informado assim que for aprovada.

Atenciosamente,
Equipe Cooperativa Camda
"""

            mail.send(msg_cliente)

        except Exception as e:
            print("Erro ao enviar e-mail:", e)

        return render_template("primeiro_acesso.html", sucesso="Solicitação enviada para análise.")

    return render_template("primeiro_acesso.html")


if __name__ == "__main__":
    app.run(debug=True)