"""
=============================================================
  database.py — Camada de dados
  SEDRA GUT V1.0626

  Expõe a mesma API que o Flask-SQLAlchemy oferecia (db.session,
  Model.query, db.get_or_404, db.create_all/drop_all) mas guarda
  os dados numa planilha Google Sheets (produção) ou em memória
  (dev local sem credenciais / testes automatizados / CI).

  O backend é escolhido automaticamente:
    - GOOGLE_SHEET_ID + GOOGLE_CREDENTIALS_JSON definidos → Google Sheets
    - Caso contrário → dicionário em memória (não persiste entre execuções)
=============================================================
"""

import os
from datetime import datetime, date

from flask import g, abort
from flask_login import UserMixin


# ══════════════════════════════════════════════════════════════
#  Infraestrutura do ORM mínimo (Column, Query, Session)
# ══════════════════════════════════════════════════════════════

class Column:
    """Descritor simples usado só para order_by(Model.campo[.desc()])."""

    def __init__(self, name):
        self.name = name

    def desc(self):
        return SortSpec(self.name, "desc")

    def asc(self):
        return SortSpec(self.name, "asc")


class SortSpec:
    def __init__(self, name, direction):
        self.name = name
        self.direction = direction


class _FuncCall:
    """Suporta o único uso de expressão do app: db.func.lower(Categoria.nome) == valor"""

    def __init__(self, column):
        self.column = column

    def __eq__(self, other):
        return _Predicate(self.column.name, other)


class _Predicate:
    def __init__(self, field, value):
        self.field = field
        self.value = value

    def matches(self, obj):
        v = getattr(obj, self.field, None)
        return (v or "").lower() == self.value


class _Func:
    @staticmethod
    def lower(column):
        return _FuncCall(column)


class Query:
    """Query encadeável, imutável (cada método devolve uma cópia)."""

    def __init__(self, model):
        self.model = model
        self._predicates = []
        self._order = None
        self._limit = None

    def _clone(self):
        q = Query(self.model)
        q._predicates = list(self._predicates)
        q._order = self._order
        q._limit = self._limit
        return q

    def filter_by(self, **kwargs):
        q = self._clone()

        def pred(obj, kwargs=kwargs):
            return all(getattr(obj, k, None) == v for k, v in kwargs.items())

        q._predicates.append(pred)
        return q

    def filter(self, predicate):
        q = self._clone()
        q._predicates.append(predicate.matches)
        return q

    def order_by(self, arg):
        q = self._clone()
        q._order = arg if isinstance(arg, SortSpec) else SortSpec(arg.name, "asc")
        return q

    def limit(self, n):
        q = self._clone()
        q._limit = n
        return q

    def _all_unlimited(self):
        rows = _backend().load(self.model)
        for pred in self._predicates:
            rows = [r for r in rows if pred(r)]
        if self._order:
            field, direction = self._order.name, self._order.direction
            rows = sorted(
                rows,
                key=lambda r: (getattr(r, field) is None, getattr(r, field)),
                reverse=(direction == "desc"),
            )
        return rows

    def all(self):
        rows = self._all_unlimited()
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows

    def first(self):
        rows = self._all_unlimited()
        obj = rows[0] if rows else None
        if obj is not None:
            _track(obj)
        return obj

    def count(self):
        return len(self._all_unlimited())


def _g_list(name):
    if not hasattr(g, name):
        setattr(g, name, [])
    return getattr(g, name)


def _track(obj):
    lst = _g_list("_sheetdb_tracked")
    if not any(o is obj for o in lst):
        lst.append(obj)


class _Session:
    def add(self, obj):
        _g_list("_sheetdb_new").append(obj)
        _track(obj)

    def delete(self, obj):
        _g_list("_sheetdb_deleted").append(obj)

    def get(self, model, id_):
        obj = _backend().get(model, id_)
        if obj is not None:
            _track(obj)
        return obj

    def commit(self):
        backend = _backend()
        new_list = _g_list("_sheetdb_new")
        deleted_list = _g_list("_sheetdb_deleted")
        tracked = _g_list("_sheetdb_tracked")

        for obj in deleted_list:
            if isinstance(obj, Tarefa):
                for h in HistoricoTarefa.query.filter_by(tarefa_id=obj.id).all():
                    backend.delete(h)
            backend.delete(obj)
            tracked[:] = [o for o in tracked if o is not obj]
            new_list[:] = [o for o in new_list if o is not obj]

        for obj in new_list:
            backend.insert(obj)
            obj._mark_clean()

        for obj in tracked:
            if obj._dirty:
                backend.update(obj)
                obj._mark_clean()

        new_list.clear()
        deleted_list.clear()

    def rollback(self):
        _g_list("_sheetdb_new").clear()
        _g_list("_sheetdb_deleted").clear()


class SheetModel:
    __tablename__ = None
    __fields__ = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.query = Query(cls)
        cls.id = Column("id")
        for name in cls.__fields__:
            setattr(cls, name, Column(name))

    def __init__(self, **kwargs):
        object.__setattr__(self, "_dirty", False)
        object.__setattr__(self, "id", kwargs.get("id"))
        for name, (type_, default) in self.__fields__.items():
            if name in kwargs:
                value = kwargs[name]
            else:
                value = default() if callable(default) else default
            object.__setattr__(self, name, value)
        self._dirty = True

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name != "_dirty":
            object.__setattr__(self, "_dirty", True)

    def _mark_clean(self):
        object.__setattr__(self, "_dirty", False)

    def _row_dict(self):
        d = {"id": self.id}
        for name in self.__fields__:
            d[name] = getattr(self, name)
        return d


# ══════════════════════════════════════════════════════════════
#  Backend: memória (dev local / testes / CI)
# ══════════════════════════════════════════════════════════════

class MemoryBackend:
    def __init__(self):
        self.tables = {}

    def _table(self, model):
        return self.tables.setdefault(model.__tablename__, [])

    def _next_id(self, model):
        rows = self._table(model)
        return max((r["id"] for r in rows), default=0) + 1

    def _to_obj(self, model, row):
        obj = model(**{k: v for k, v in row.items() if k != "id"})
        object.__setattr__(obj, "id", row["id"])
        obj._mark_clean()
        return obj

    def load(self, model):
        return [self._to_obj(model, dict(r)) for r in self._table(model)]

    def get(self, model, id_):
        if id_ is None:
            return None
        for r in self._table(model):
            if r["id"] == int(id_):
                return self._to_obj(model, dict(r))
        return None

    def insert(self, obj):
        model = type(obj)
        rows = self._table(model)
        object.__setattr__(obj, "id", self._next_id(model))
        rows.append(obj._row_dict())

    def update(self, obj):
        model = type(obj)
        rows = self._table(model)
        for i, r in enumerate(rows):
            if r["id"] == obj.id:
                rows[i] = obj._row_dict()
                return

    def delete(self, obj):
        model = type(obj)
        self.tables[model.__tablename__] = [
            r for r in self._table(model) if r["id"] != obj.id
        ]

    def clear(self):
        self.tables = {}


# ══════════════════════════════════════════════════════════════
#  Backend: Google Sheets (produção)
# ══════════════════════════════════════════════════════════════

def _serialize_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _deserialize_value(raw, type_, default):
    if raw is None or str(raw).strip() == "":
        return default() if callable(default) else default
    if type_ is bool:
        return str(raw).strip().lower() in ("1", "true")
    if type_ is int:
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            return default() if callable(default) else default
    if type_ is float:
        try:
            return float(raw)
        except (ValueError, TypeError):
            return default() if callable(default) else default
    if type_ is date:
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            return default() if callable(default) else default
    if type_ is datetime:
        s = str(raw)
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            try:
                return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return default() if callable(default) else default
    return str(raw)


_spreadsheet_cache = None


def _get_spreadsheet():
    global _spreadsheet_cache
    if _spreadsheet_cache is not None:
        return _spreadsheet_cache
    import json
    import gspread
    from google.oauth2.service_account import Credentials

    creds_info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)
    _spreadsheet_cache = client.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    return _spreadsheet_cache


class SheetsBackend:
    """
    Cacheia as linhas de cada aba em memória de processo (self._data_cache) para
    não estourar a cota de leituras da API do Sheets (60/min por usuário) — cada
    página do app faz várias consultas, e sem cache cada uma seria uma chamada
    de rede. O cache de uma aba só é invalidado quando o próprio app escreve
    nela (insert/update/delete); edições feitas direto na planilha por uma
    pessoa não aparecem até a próxima escrita do app ou reinício do processo.
    """

    def __init__(self):
        self._ws_cache = {}
        self._data_cache = {}

    def _worksheet(self, model):
        if model.__tablename__ in self._ws_cache:
            return self._ws_cache[model.__tablename__]
        import gspread

        ss = _get_spreadsheet()
        headers = ["id"] + list(model.__fields__.keys())
        try:
            ws = ss.worksheet(model.__tablename__)
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(
                title=model.__tablename__, rows=200, cols=len(headers) + 2
            )
            ws.append_row(headers)
        existing_headers = ws.row_values(1)
        if existing_headers != headers:
            ws.update("A1", [headers])
        self._ws_cache[model.__tablename__] = ws
        return ws

    def _data_rows(self, model):
        name = model.__tablename__
        if name not in self._data_cache:
            ws = self._worksheet(model)
            values = ws.get_all_values()
            self._data_cache[name] = values[1:] if len(values) > 1 else []
        return self._data_cache[name]

    def _invalidate(self, model):
        self._data_cache.pop(model.__tablename__, None)

    def _to_obj(self, model, row):
        headers = ["id"] + list(model.__fields__.keys())
        rec = dict(zip(headers, row + [""] * (len(headers) - len(row))))
        kwargs = {}
        for name, (type_, default) in model.__fields__.items():
            kwargs[name] = _deserialize_value(rec.get(name, ""), type_, default)
        obj = model(**kwargs)
        raw_id = rec.get("id", "")
        object.__setattr__(obj, "id", int(raw_id) if str(raw_id).strip() else None)
        obj._mark_clean()
        return obj

    def load(self, model):
        return [self._to_obj(model, row) for row in self._data_rows(model)]

    def get(self, model, id_):
        if id_ is None:
            return None
        for row in self._data_rows(model):
            if row and str(row[0]).strip() == str(id_):
                return self._to_obj(model, row)
        return None

    def _serialize_row(self, obj):
        row = [str(obj.id)]
        for name in type(obj).__fields__:
            row.append(_serialize_value(getattr(obj, name)))
        return row

    def insert(self, obj):
        model = type(obj)
        ws = self._worksheet(model)
        rows = self._data_rows(model)
        existing_ids = [
            int(r[0]) for r in rows if r and str(r[0]).strip().isdigit()
        ]
        object.__setattr__(obj, "id", (max(existing_ids) if existing_ids else 0) + 1)
        ws.append_row(self._serialize_row(obj), value_input_option="RAW")
        self._invalidate(model)

    def update(self, obj):
        model = type(obj)
        ws = self._worksheet(model)
        rows = self._data_rows(model)
        for idx, row in enumerate(rows, start=2):
            if row and str(row[0]).strip() == str(obj.id):
                ws.update(f"A{idx}", [self._serialize_row(obj)])
                self._invalidate(model)
                return

    def delete(self, obj):
        model = type(obj)
        ws = self._worksheet(model)
        rows = self._data_rows(model)
        for idx, row in enumerate(rows, start=2):
            if row and str(row[0]).strip() == str(obj.id):
                ws.delete_rows(idx)
                self._invalidate(model)
                return


# ══════════════════════════════════════════════════════════════
#  Seleção de backend
# ══════════════════════════════════════════════════════════════

_memory_backend_instance = None
_sheets_backend_instance = None


def _using_sheets():
    return bool(os.environ.get("GOOGLE_SHEET_ID")) and bool(
        os.environ.get("GOOGLE_CREDENTIALS_JSON")
    )


def _backend():
    global _memory_backend_instance, _sheets_backend_instance
    if _using_sheets():
        if _sheets_backend_instance is None:
            _sheets_backend_instance = SheetsBackend()
        return _sheets_backend_instance
    if _memory_backend_instance is None:
        _memory_backend_instance = MemoryBackend()
    return _memory_backend_instance


class _DB:
    session = _Session()
    func = _Func()

    def init_app(self, app):
        pass

    def create_all(self):
        backend = _backend()
        for model in _ALL_MODELS:
            if isinstance(backend, SheetsBackend):
                backend._worksheet(model)

    def drop_all(self):
        backend = _backend()
        if isinstance(backend, MemoryBackend):
            backend.clear()
        else:
            for model in _ALL_MODELS:
                ws = backend._worksheet(model)
                ws.clear()
                ws.append_row(["id"] + list(model.__fields__.keys()))

    def get_or_404(self, model, id_):
        obj = _backend().get(model, id_)
        if obj is None:
            abort(404)
        _track(obj)
        return obj


db = _DB()


# ══════════════════════════════════════════════════════════════
#  Modelos
# ══════════════════════════════════════════════════════════════

class Usuario(UserMixin, SheetModel):
    """
    Tabela de usuários.
    perfil pode ser: "administrador", "operador" ou "visitante"
    """
    __tablename__ = "usuarios"
    __fields__ = {
        "nome": (str, ""),
        "email": (str, ""),
        "senha_hash": (str, ""),
        "perfil": (str, "operador"),
        "ativo": (bool, True),
        "criado_em": (datetime, datetime.utcnow),
    }

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


class Categoria(SheetModel):
    """
    Categorias de tarefas.
    Operadores podem criar, mas ficam inativas até o admin aprovar.
    """
    __tablename__ = "categorias"
    __fields__ = {
        "nome": (str, ""),
        "ativa": (bool, False),
        "criado_por": (str, ""),
        "criado_em": (datetime, datetime.utcnow),
    }

    def __repr__(self):
        status = "ativa" if self.ativa else "pendente"
        return f"<Categoria {self.nome} [{status}]>"


class Configuracao(SheetModel):
    """
    Configurações gerais do sistema (logo, nome da empresa, etc).
    Funciona como um dicionário chave→valor.
    Exemplo: chave="logo_filename", valor="logo_sedra.png"
    """
    __tablename__ = "configuracoes"
    __fields__ = {
        "chave": (str, ""),
        "valor": (str, ""),
    }

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


class Tarefa(SheetModel):
    """
    Tabela de tarefas da Matriz GUT.
    """
    __tablename__ = "tarefas"
    __fields__ = {
        "titulo": (str, ""),
        "descricao": (str, ""),
        "responsavel": (str, ""),
        "categoria": (str, "Geral"),
        "gravidade": (int, 1),
        "urgencia": (int, 1),
        "tendencia": (int, 1),
        "prioridade": (int, 1),
        "status": (str, "Pendente"),
        "prazo": (date, None),
        "exportado_board": (bool, False),
        "board_status": (str, None),
        "board_ordem": (int, 0),
        "etiquetas": (str, ""),
        "estimativa_h": (float, None),
        "criado_por_id": (int, None),
        "criado_por": (str, ""),
        "criado_em": (datetime, datetime.utcnow),
        "atualizado_em": (datetime, datetime.utcnow),
    }

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


class HistoricoTarefa(SheetModel):
    """Registro de cada modificação feita em uma tarefa."""
    __tablename__ = "historico_tarefas"
    __fields__ = {
        "tarefa_id": (int, None),
        "usuario_id": (int, None),
        "usuario_nome": (str, ""),
        "descricao": (str, ""),
        "criado_em": (datetime, datetime.utcnow),
    }

    def __repr__(self):
        return f"<Historico tarefa={self.tarefa_id} '{self.descricao[:30]}'>"


class Atividade(SheetModel):
    """
    Log de tudo que acontece no sistema — exibido na barra lateral.
    """
    __tablename__ = "atividades"
    __fields__ = {
        "descricao": (str, ""),
        "usuario_id": (int, None),
        "usuario_nome": (str, ""),
        "criado_em": (datetime, datetime.utcnow),
    }

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


_ALL_MODELS = [Usuario, Categoria, Configuracao, Tarefa, HistoricoTarefa, Atividade]
