"""
=============================================================
  database.py — Modelos do Banco de Dados
  SEDRA GUT V1.0626
=============================================================
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class Usuario(UserMixin, db.Model):
    """
    Tabela de usuários.
    perfil pode ser: "administrador", "operador" ou "visitante"
    """
    __tablename__ = "usuarios"

    id          = db.Column(db.Integer, primary_key=True)
    nome        = db.Column(db.String(100), nullable=False)
    email       = db.Column(db.String(150), unique=True, nullable=False)
    senha_hash  = db.Column(db.String(256), nullable=False)
    perfil      = db.Column(db.String(20), default="operador")
    ativo       = db.Column(db.Boolean, default=True)
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)

    # Atalhos para verificar o perfil de forma legível no código
    @property
    def eh_admin(self):
        return self.perfil == "administrador"

    @property
    def eh_operador(self):
        return self.perfil == "operador"

    @property
    def eh_visitante(self):
        return self.perfil == "visitante"

    def __repr__(self):
        return f"<Usuario {self.nome} [{self.perfil}]>"


class Categoria(db.Model):
    """
    Categorias de tarefas.
    Operadores podem criar, mas ficam inativas até o admin aprovar.
    """
    __tablename__ = "categorias"

    id           = db.Column(db.Integer, primary_key=True)
    nome         = db.Column(db.String(80), nullable=False, unique=True)
    ativa        = db.Column(db.Boolean, default=False)
    # False = aguardando aprovação do admin | True = disponível para uso
    criado_por   = db.Column(db.String(100), default="")
    criado_em    = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        status = "ativa" if self.ativa else "pendente"
        return f"<Categoria {self.nome} [{status}]>"


class Configuracao(db.Model):
    """
    Configurações gerais do sistema (logo, nome da empresa, etc).
    Funciona como um dicionário chave→valor no banco de dados.
    Exemplo: chave="logo_filename", valor="logo_sedra.png"
    """
    __tablename__ = "configuracoes"

    id    = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.String(500), default="")

    @staticmethod
    def get(chave, padrao=""):
        """Busca o valor de uma configuração pelo nome da chave."""
        cfg = Configuracao.query.filter_by(chave=chave).first()
        return cfg.valor if cfg else padrao

    @staticmethod
    def set(chave, valor):
        """Salva ou atualiza uma configuração."""
        cfg = Configuracao.query.filter_by(chave=chave).first()
        if cfg:
            cfg.valor = valor
        else:
            cfg = Configuracao(chave=chave, valor=valor)
            db.session.add(cfg)
        db.session.commit()

    def __repr__(self):
        return f"<Config {self.chave}={self.valor}>"


class Tarefa(db.Model):
    """
    Tabela de tarefas da Matriz GUT.
    """
    __tablename__ = "tarefas"

    id              = db.Column(db.Integer, primary_key=True)
    titulo          = db.Column(db.String(200), nullable=False)
    descricao       = db.Column(db.Text, default="")
    responsavel     = db.Column(db.String(100), default="")
    categoria       = db.Column(db.String(80), default="Geral")

    # Notas GUT
    gravidade       = db.Column(db.Integer, nullable=False, default=1)
    urgencia        = db.Column(db.Integer, nullable=False, default=1)
    tendencia       = db.Column(db.Integer, nullable=False, default=1)
    prioridade      = db.Column(db.Integer, nullable=False, default=1)

    # Status — só admin pode mudar para "Em andamento"
    status          = db.Column(db.String(20), default="Pendente")

    # Campos para integração futura com o SEDRA BOARD
    prazo           = db.Column(db.Date, nullable=True)
    exportado_board = db.Column(db.Boolean, default=False)
    board_status    = db.Column(db.String(30), nullable=True)
    board_ordem     = db.Column(db.Integer, default=0)
    etiquetas       = db.Column(db.String(200), default="")
    estimativa_h    = db.Column(db.Float, nullable=True)

    # Auditoria — guarda quem criou (id e nome) para controle de permissões
    criado_por_id   = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    criado_por      = db.Column(db.String(100), default="")
    criado_em       = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em   = db.Column(db.DateTime, default=datetime.utcnow,
                                onupdate=datetime.utcnow)

    def nivel_prioridade(self):
        if self.prioridade >= 75:
            return ("Crítica", "danger")
        elif self.prioridade >= 40:
            return ("Alta", "warning")
        elif self.prioridade >= 15:
            return ("Média", "info")
        else:
            return ("Baixa", "secondary")

    def lista_etiquetas(self):
        if not self.etiquetas:
            return []
        return [e.strip() for e in self.etiquetas.split(",") if e.strip()]

    def para_board(self):
        return {
            "id_origem":    self.id,
            "titulo":       self.titulo,
            "descricao":    self.descricao,
            "responsavel":  self.responsavel,
            "categoria":    self.categoria,
            "prioridade":   self.prioridade,
            "nivel":        self.nivel_prioridade()[0],
            "prazo":        self.prazo.isoformat() if self.prazo else None,
            "etiquetas":    self.lista_etiquetas(),
            "estimativa_h": self.estimativa_h,
            "criado_por":   self.criado_por,
        }

    def __repr__(self):
        return f"<Tarefa '{self.titulo}' GUT={self.prioridade}>"


class HistoricoTarefa(db.Model):
    """Registro de cada modificação feita em uma tarefa."""
    __tablename__ = "historico_tarefas"

    id           = db.Column(db.Integer, primary_key=True)
    tarefa_id    = db.Column(db.Integer, db.ForeignKey("tarefas.id", ondelete="CASCADE"), nullable=False)
    usuario_id   = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    usuario_nome = db.Column(db.String(100), default="")
    descricao    = db.Column(db.String(400), nullable=False)
    criado_em    = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Historico tarefa={self.tarefa_id} '{self.descricao[:30]}'>"


class Atividade(db.Model):
    """
    Log de tudo que acontece no sistema — exibido na barra lateral.
    """
    __tablename__ = "atividades"

    id           = db.Column(db.Integer, primary_key=True)
    descricao    = db.Column(db.String(300), nullable=False)
    usuario_id   = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    usuario_nome = db.Column(db.String(100), default="")
    criado_em    = db.Column(db.DateTime, default=datetime.utcnow)

    def tempo_relativo(self):
        delta = datetime.utcnow() - self.criado_em
        s = int(delta.total_seconds())
        if s < 60:
            return "agora mesmo"
        elif s < 3600:
            return f"{s // 60} min atrás"
        elif s < 86400:
            return f"{s // 3600}h atrás"
        else:
            return f"{s // 86400}d atrás"

    def __repr__(self):
        return f"<Atividade '{self.descricao[:30]}'>"
