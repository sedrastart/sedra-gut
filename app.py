"""
=============================================================
  SEDRA GUT — Matriz de Priorização de Tarefas
  Versão: V1.0626
=============================================================
"""

import os
from flask import (Flask, render_template, request, redirect,
                   url_for, flash, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
from database import db, Usuario, Tarefa, Atividade, Categoria, Configuracao, HistoricoTarefa
from functools import wraps

# ── Configuração ───────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "sedra_gut_chave_secreta_2026"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = (
    "sqlite:///" + os.path.join(BASE_DIR, "instance", "sedra_gut.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB máximo para logo

os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para acessar o sistema."
login_manager.login_message_category = "warning"

EXTENSOES_PERMITIDAS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}


# ── Helpers ────────────────────────────────────────────────────

@login_manager.user_loader
def carregar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


def registrar_atividade(descricao):
    a = Atividade(
        descricao=descricao,
        usuario_id=current_user.id,
        usuario_nome=current_user.nome
    )
    db.session.add(a)
    db.session.commit()


def registrar_historico(tarefa_id, descricao):
    h = HistoricoTarefa(
        tarefa_id=tarefa_id,
        usuario_id=current_user.id,
        usuario_nome=current_user.nome,
        descricao=descricao
    )
    db.session.add(h)


def extensao_permitida(filename):
    return ("." in filename and
            filename.rsplit(".", 1)[1].lower() in EXTENSOES_PERMITIDAS)


# ── Decoradores de permissão ───────────────────────────────────

def requer_admin(f):
    """Bloqueia a rota para quem não for administrador."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.eh_admin:
            flash("Acesso restrito a administradores.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def requer_operador_ou_admin(f):
    """Bloqueia visitantes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.eh_visitante:
            flash("Visitantes não podem realizar esta ação.", "warning")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ── Context processor — injeta dados globais nos templates ─────

@app.context_processor
def injetar_globais():
    """
    Tudo que for retornado aqui fica disponível em TODOS os templates
    sem precisar passar manualmente em cada render_template().
    """
    logo = Configuracao.get("logo_filename", "")
    nome_empresa = Configuracao.get("nome_empresa", "SEDRA GUT")
    # Categorias pendentes (para badge no ícone de config)
    pendentes_cat = 0
    atividades = []
    if current_user.is_authenticated:
        if current_user.eh_admin:
            pendentes_cat = Categoria.query.filter_by(ativa=False).count()
        atividades = (Atividade.query
                      .order_by(Atividade.criado_em.desc())
                      .limit(20).all())
    from datetime import date
    return dict(
        logo_filename=logo,
        nome_empresa=nome_empresa,
        pendentes_cat=pendentes_cat,
        hoje=date.today(),
        atividades=atividades
    )


# ══════════════════════════════════════════════════════════════
#  ROTAS: Autenticação
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user.is_authenticated
                    else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter_by(email=email, ativo=True).first()
        if usuario and check_password_hash(usuario.senha_hash, senha):
            login_user(usuario, remember=True)
            a = Atividade(descricao="Login realizado",
                          usuario_id=usuario.id, usuario_nome=usuario.nome)
            db.session.add(a)
            db.session.commit()
            flash(f"Bem-vindo(a), {usuario.nome}!", "success")
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha incorretos.", "danger")
    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    # Só permite auto-cadastro se não houver nenhum usuário ainda
    # (criação do primeiro admin). Depois, apenas admins criam usuários.
    tem_usuarios = Usuario.query.count() > 0
    if tem_usuarios and (not current_user.is_authenticated or not current_user.eh_admin):
        flash("Novos cadastros devem ser feitos pelo administrador.", "warning")
        return redirect(url_for("login"))

    if request.method == "POST":
        nome     = request.form.get("nome", "").strip()
        email    = request.form.get("email", "").strip().lower()
        senha    = request.form.get("senha", "")
        confirma = request.form.get("confirma_senha", "")
        perfil   = request.form.get("perfil", "operador")

        if not nome or not email or not senha:
            flash("Preencha todos os campos.", "warning")
        elif senha != confirma:
            flash("As senhas não coincidem.", "danger")
        elif len(senha) < 6:
            flash("Senha deve ter pelo menos 6 caracteres.", "warning")
        elif Usuario.query.filter_by(email=email).first():
            flash("Este e-mail já está cadastrado.", "warning")
        else:
            # Primeiro usuário vira admin automaticamente
            if not tem_usuarios:
                perfil = "administrador"
            novo = Usuario(nome=nome, email=email,
                           senha_hash=generate_password_hash(senha),
                           perfil=perfil)
            db.session.add(novo)
            db.session.commit()
            if current_user.is_authenticated:
                registrar_atividade(f"Usuário criado: {nome} [{perfil}]")
                flash(f"Usuário {nome} criado com sucesso!", "success")
                return redirect(url_for("config_usuarios"))
            else:
                flash("Conta criada! Faça login.", "success")
                return redirect(url_for("login"))

    return render_template("cadastro.html")


@app.route("/logout")
@login_required
def logout():
    registrar_atividade("Logout realizado")
    logout_user()
    flash("Você saiu do sistema.", "info")
    return redirect(url_for("login"))

# ══════════════════════════════════════════════════════════════
#  ROTAS: Dashboard e Tarefas
# ══════════════════════════════════════════════════════════════

@app.route("/dashboard")
@login_required
def dashboard():
    tarefas    = Tarefa.query.order_by(Tarefa.prioridade.desc()).all()
    atividades = Atividade.query.order_by(
                     Atividade.criado_em.desc()).limit(20).all()
    # Categorias ativas em ordem alfabética para o formulário
    categorias = (Categoria.query
                  .filter_by(ativa=True)
                  .order_by(Categoria.nome)
                  .all())
    hoje = date.today()
    usuarios = Usuario.query.filter_by(ativo=True).order_by(Usuario.nome).all()
    return render_template('dashboard.html', tarefas=tarefas, categorias=categorias, hoje=hoje, usuarios=usuarios)
  
@app.route("/tarefa/nova", methods=["POST"])
@login_required
@requer_operador_ou_admin
def nova_tarefa():
    titulo      = request.form.get("titulo", "").strip()
    descricao   = request.form.get("descricao", "").strip()
    responsavel = request.form.get("responsavel", "").strip()
    categoria   = request.form.get("categoria", "Geral").strip()
    prazo_str   = request.form.get("prazo", "").strip()

    try:
        g = max(1, min(5, int(request.form.get("gravidade", 1))))
        u = max(1, min(5, int(request.form.get("urgencia", 1))))
        t = max(1, min(5, int(request.form.get("tendencia", 1))))
    except (ValueError, TypeError):
        flash("Notas GUT inválidas.", "danger")
        return redirect(url_for("dashboard"))

    if not titulo:
        flash("O título é obrigatório.", "warning")
        return redirect(url_for("dashboard"))

    prazo = None
    if prazo_str:
        try:
            prazo = datetime.strptime(prazo_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    tarefa = Tarefa(
        titulo=titulo, descricao=descricao,
        responsavel=responsavel, categoria=categoria,
        gravidade=g, urgencia=u, tendencia=t,
        prioridade=g * u * t,
        prazo=prazo,
        criado_por_id=current_user.id,
        criado_por=current_user.nome
    )
    db.session.add(tarefa)
    db.session.commit()
    registrar_historico(tarefa.id, f'Tarefa criada com GUT {g}×{u}×{t} = {g*u*t}')
    db.session.commit()
    registrar_atividade(f'Tarefa criada: "{titulo}" (GUT: {g*u*t})')
    flash(f'Tarefa "{titulo}" criada!', "success")
    return redirect(url_for("dashboard"))


@app.route("/tarefa/<int:id>/editar", methods=["GET", "POST"])
@login_required
def editar_tarefa(id):
    tarefa = db.get_or_404(Tarefa, id)

    # Visitante não pode editar nada
    if current_user.eh_visitante:
        flash("Visitantes não podem editar tarefas.", "warning")
        return redirect(url_for("dashboard"))

    # Operador só edita suas próprias tarefas
    if current_user.eh_operador and tarefa.criado_por_id != current_user.id:
        flash("Você só pode editar tarefas que criou.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        novo_status = request.form.get("status", tarefa.status)

        # Operador não pode mudar status para "Em andamento" ou "Concluída"
        if current_user.eh_operador and novo_status != "Pendente":
            flash("Apenas administradores podem alterar o status da tarefa.", "warning")
            novo_status = tarefa.status

        tarefa.titulo      = request.form.get("titulo", tarefa.titulo).strip()
        tarefa.descricao   = request.form.get("descricao", "").strip()
        tarefa.responsavel = request.form.get("responsavel", "").strip()
        tarefa.categoria   = request.form.get("categoria", "Geral").strip()
        tarefa.status      = novo_status

        prazo_str = request.form.get("prazo", "")
        if prazo_str:
            try:
                tarefa.prazo = datetime.strptime(prazo_str, "%Y-%m-%d").date()
            except ValueError:
                pass
        else:
            tarefa.prazo = None

        try:
            tarefa.gravidade = max(1, min(5, int(request.form.get("gravidade", 1))))
            tarefa.urgencia  = max(1, min(5, int(request.form.get("urgencia", 1))))
            tarefa.tendencia = max(1, min(5, int(request.form.get("tendencia", 1))))
        except (ValueError, TypeError):
            flash("Notas GUT inválidas.", "danger")
            return redirect(url_for("dashboard"))

        tarefa.prioridade    = tarefa.gravidade * tarefa.urgencia * tarefa.tendencia
        tarefa.atualizado_em = datetime.utcnow()
        partes = [f'Status: {novo_status}'] if novo_status != tarefa.status else []
        partes.append(f'GUT: {tarefa.gravidade}×{tarefa.urgencia}×{tarefa.tendencia} = {tarefa.prioridade}')
        registrar_historico(tarefa.id, 'Tarefa editada — ' + ' | '.join(partes))
        db.session.commit()
        registrar_atividade(f'Tarefa editada: "{tarefa.titulo}"')
        flash("Tarefa atualizada!", "success")
        return redirect(url_for("dashboard"))

    # GET — retorna JSON para o modal de edição (inclui histórico)
    historico = (HistoricoTarefa.query
                 .filter_by(tarefa_id=tarefa.id)
                 .order_by(HistoricoTarefa.criado_em.desc())
                 .all())
    return jsonify({
        "id": tarefa.id, "titulo": tarefa.titulo,
        "descricao": tarefa.descricao, "responsavel": tarefa.responsavel,
        "categoria": tarefa.categoria, "gravidade": tarefa.gravidade,
        "urgencia": tarefa.urgencia, "tendencia": tarefa.tendencia,
        "status": tarefa.status,
        "prazo": tarefa.prazo.isoformat() if tarefa.prazo else "",
        "criado_por_id": tarefa.criado_por_id,
        "historico": [
            {
                "descricao": h.descricao,
                "usuario": h.usuario_nome,
                "data": h.criado_em.strftime("%d/%m/%Y %H:%M")
            }
            for h in historico
        ]
    })


@app.route("/tarefa/<int:id>/excluir", methods=["POST"])
@login_required
def excluir_tarefa(id):
    tarefa = db.get_or_404(Tarefa, id)

    if current_user.eh_visitante:
        flash("Visitantes não podem excluir tarefas.", "warning")
        return redirect(url_for("dashboard"))

    if current_user.eh_operador and tarefa.criado_por_id != current_user.id:
        flash("Você só pode excluir tarefas que criou.", "warning")
        return redirect(url_for("dashboard"))

    titulo = tarefa.titulo
    db.session.delete(tarefa)
    db.session.commit()
    registrar_atividade(f'Tarefa excluída: "{titulo}"')
    flash(f'Tarefa "{titulo}" removida.', "info")
    return redirect(url_for("dashboard"))


@app.route("/tarefa/<int:id>/concluir", methods=["POST"])
@login_required
@requer_admin
def concluir_tarefa(id):
    tarefa = db.get_or_404(Tarefa, id)
    tarefa.status = "Concluída"
    tarefa.atualizado_em = datetime.utcnow()
    registrar_historico(tarefa.id, 'Status alterado para: Concluída')
    db.session.commit()
    registrar_atividade(f'Tarefa concluída: "{tarefa.titulo}"')
    flash(f'Tarefa "{tarefa.titulo}" concluída!', "success")
    return redirect(url_for("dashboard"))


@app.route("/tarefa/<int:id>/iniciar", methods=["POST"])
@login_required
@requer_admin
def iniciar_tarefa(id):
    tarefa = db.get_or_404(Tarefa, id)
    tarefa.status = "Em andamento"
    tarefa.atualizado_em = datetime.utcnow()
    registrar_historico(tarefa.id, 'Status alterado para: Em andamento')
    db.session.commit()
    registrar_atividade(f'Tarefa iniciada: "{tarefa.titulo}"')
    flash(f'Tarefa "{tarefa.titulo}" em andamento!', "success")
    return redirect(url_for("dashboard"))


# ══════════════════════════════════════════════════════════════
#  ROTAS: Configurações (só admin)
# ══════════════════════════════════════════════════════════════

@app.route("/configuracoes")
@login_required
@requer_admin
def configuracoes():
    return render_template("configuracoes.html")


# ── Usuários ───────────────────────────────────────────────────

@app.route("/configuracoes/usuarios")
@login_required
@requer_admin
def config_usuarios():
    usuarios = Usuario.query.order_by(Usuario.nome).all()
    return render_template("config_usuarios.html", usuarios=usuarios)


@app.route("/configuracoes/usuarios/<int:id>/editar", methods=["POST"])
@login_required
@requer_admin
def editar_usuario(id):
    usuario = db.get_or_404(Usuario, id)
    # Impede que o admin remova seu próprio perfil de admin
    if usuario.id == current_user.id and request.form.get("perfil") != "administrador":
        flash("Você não pode alterar seu próprio perfil de administrador.", "warning")
        return redirect(url_for("config_usuarios"))

    usuario.nome   = request.form.get("nome", usuario.nome).strip()
    usuario.perfil = request.form.get("perfil", usuario.perfil)
    usuario.ativo  = request.form.get("ativo") == "1"
    db.session.commit()
    registrar_atividade(f"Usuário editado: {usuario.nome} [{usuario.perfil}]")
    flash(f"Usuário {usuario.nome} atualizado.", "success")
    return redirect(url_for("config_usuarios"))


@app.route("/configuracoes/usuarios/<int:id>/redefinir-senha", methods=["POST"])
@login_required
@requer_admin
def redefinir_senha(id):
    usuario = db.get_or_404(Usuario, id)
    nova_senha = request.form.get("nova_senha", "")
    if len(nova_senha) < 6:
        flash("A nova senha deve ter pelo menos 6 caracteres.", "warning")
        return redirect(url_for("config_usuarios"))
    usuario.senha_hash = generate_password_hash(nova_senha)
    db.session.commit()
    registrar_atividade(f"Senha redefinida para: {usuario.nome}")
    flash(f"Senha de {usuario.nome} redefinida.", "success")
    return redirect(url_for("config_usuarios"))


# ── Categorias ─────────────────────────────────────────────────

@app.route("/configuracoes/categorias")
@login_required
@requer_admin
def config_categorias():
    ativas    = (Categoria.query.filter_by(ativa=True)
                 .order_by(Categoria.nome).all())
    pendentes = (Categoria.query.filter_by(ativa=False)
                 .order_by(Categoria.nome).all())
    return render_template("config_categorias.html",
                           ativas=ativas, pendentes=pendentes)


@app.route("/configuracoes/categorias/nova", methods=["POST"])
@login_required
@requer_operador_ou_admin
def nova_categoria():
    nome = request.form.get("nome", "").strip()
    if not nome:
        flash("Informe o nome da categoria.", "warning")
        return redirect(url_for("dashboard"))

    if Categoria.query.filter(
            db.func.lower(Categoria.nome) == nome.lower()).first():
        flash("Essa categoria já existe.", "warning")
        return redirect(url_for("dashboard"))

    # Admin cria já ativa; operador cria pendente
    ativa = current_user.eh_admin
    cat = Categoria(nome=nome, ativa=ativa, criado_por=current_user.nome)
    db.session.add(cat)
    db.session.commit()

    if ativa:
        registrar_atividade(f'Categoria criada: "{nome}"')
        flash(f'Categoria "{nome}" criada.', "success")
    else:
        registrar_atividade(f'Categoria solicitada: "{nome}" (aguarda aprovação)')
        flash(f'Categoria "{nome}" enviada para aprovação do administrador.', "info")

    # Redireciona para a tela certa
    if current_user.eh_admin:
        return redirect(url_for("config_categorias"))
    return redirect(url_for("dashboard"))


@app.route("/configuracoes/categorias/<int:id>/aprovar", methods=["POST"])
@login_required
@requer_admin
def aprovar_categoria(id):
    cat = db.get_or_404(Categoria, id)
    cat.ativa = True
    db.session.commit()
    registrar_atividade(f'Categoria aprovada: "{cat.nome}"')
    flash(f'Categoria "{cat.nome}" aprovada e ativada.', "success")
    return redirect(url_for("config_categorias"))


@app.route("/configuracoes/categorias/<int:id>/excluir", methods=["POST"])
@login_required
@requer_admin
def excluir_categoria(id):
    cat = db.get_or_404(Categoria, id)
    nome = cat.nome
    db.session.delete(cat)
    db.session.commit()
    registrar_atividade(f'Categoria excluída: "{nome}"')
    flash(f'Categoria "{nome}" excluída.', "info")
    return redirect(url_for("config_categorias"))


# ── Aparência (logo) ───────────────────────────────────────────

@app.route("/configuracoes/aparencia", methods=["GET", "POST"])
@login_required
@requer_admin
def config_aparencia():
    if request.method == "POST":
        nome_empresa = request.form.get("nome_empresa", "").strip()
        if nome_empresa:
            Configuracao.set("nome_empresa", nome_empresa)

        arquivo = request.files.get("logo")
        if arquivo and arquivo.filename:
            if not extensao_permitida(arquivo.filename):
                flash("Formato inválido. Use PNG, JPG, GIF, WEBP ou SVG.", "danger")
                return redirect(url_for("config_aparencia"))

            # Remove logo antigo se existir
            logo_antigo = Configuracao.get("logo_filename")
            if logo_antigo:
                caminho_antigo = os.path.join(
                    app.config["UPLOAD_FOLDER"], logo_antigo)
                if os.path.exists(caminho_antigo):
                    os.remove(caminho_antigo)

            nome_arquivo = secure_filename(arquivo.filename)
            arquivo.save(os.path.join(app.config["UPLOAD_FOLDER"], nome_arquivo))
            Configuracao.set("logo_filename", nome_arquivo)
            registrar_atividade("Logo da empresa atualizado")

        flash("Configurações de aparência salvas.", "success")
        return redirect(url_for("config_aparencia"))

    return render_template("config_aparencia.html")


# ── Inicialização ──────────────────────────────────────────────

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # Categorias padrão (só cria se o banco estiver vazio)
        if Categoria.query.count() == 0:
            for nome in ["Financeiro", "Fiscal", "Geral", "Operacional",
                         "RH", "Comercial", "Jurídico"]:
                db.session.add(Categoria(nome=nome, ativa=True,
                                         criado_por="sistema"))
            db.session.commit()
        print("=" * 50)
        print("  SEDRA GUT — V1.0626")
        print("  Acesse: http://localhost:5000")
        print("=" * 50)
    app.run(debug=True, host="0.0.0.0", port=5000)
