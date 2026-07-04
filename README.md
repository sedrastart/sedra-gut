# SEDRA GUT — V1.0626
## Sistema de Priorização de Tarefas com Matriz GUT

---

## 📋 O que é este aplicativo?

O **SEDRA GUT** permite cadastrar e priorizar tarefas usando a **Matriz GUT**:
- **G**ravidade: qual o impacto se o problema não for resolvido? (1 a 5)
- **U**rgência: qual o prazo disponível para resolver? (1 a 5)
- **T**endência: como o problema evolui sem ação? (1 a 5)
- **Prioridade = G × U × T** (máximo: 125 pontos)

---

## 🚀 Como instalar e rodar

### Pré-requisitos
- Python 3.10 ou superior instalado
- Acesso ao terminal (Prompt de Comando ou PowerShell no Windows)

### Passo 1 — Baixe os arquivos do projeto
Coloque a pasta `sedra_gut` em qualquer local do seu computador.

### Passo 2 — Abra o terminal na pasta do projeto
```bash
cd caminho/para/sedra_gut
```

### Passo 3 — Instale as dependências (só na primeira vez)
```bash
pip install -r requirements.txt
```

### Passo 4 — Inicie o servidor
```bash
python app.py
```

### Passo 5 — Abra o navegador
Acesse: **http://localhost:5000**

---

## 👥 Uso em rede (vários usuários)

Para que outros computadores na mesma rede acessem o sistema:

1. Descubra o IP do computador que está rodando o servidor:
   - Windows: `ipconfig` no terminal → procure "Endereço IPv4"
   - Ex: `192.168.1.10`

2. Os outros usuários acessam pelo navegador:
   ```
   http://192.168.1.10:5000
   ```

3. O servidor deve estar rodando no computador "principal" enquanto os outros usam.

---

## 🗂️ Estrutura do projeto

```
sedra_gut/
├── app.py          ← Servidor principal (lógica das páginas)
├── database.py     ← Camada de dados (Google Sheets ou memória)
├── requirements.txt← Dependências Python
├── vercel.json     ← Configuração de deploy no Vercel
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── cadastro.html
│   ├── dashboard.html
│   ├── configuracoes.html
│   ├── config_usuarios.html
│   ├── config_categorias.html
│   └── config_aparencia.html
└── static/
    ├── style.css
    └── script.js
```

---

## ☁️ Deploy no Vercel + Google Sheets como banco de dados

O banco de dados desta versão é uma planilha do Google Sheets (via API), lida/gravada
através do módulo `database.py`. Se as variáveis de ambiente do Google não estiverem
configuradas, o sistema usa automaticamente um banco em memória (útil para rodar
localmente sem depender do Google, e é o que os testes automatizados/CI usam).

### 1. Criar a Service Account no Google Cloud
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/) e crie um projeto
2. Ative a **Google Sheets API** (menu "APIs e Serviços" → "Ativar APIs e Serviços")
3. Crie uma **Service Account** ("Credenciais" → "Criar credenciais" → "Conta de serviço")
4. Na service account criada, gere uma **chave JSON** (aba "Chaves" → "Adicionar chave" → JSON) e baixe o arquivo

### 2. Criar e compartilhar a planilha
1. Crie uma planilha nova em branco no Google Sheets
2. Copie o **ID da planilha** (está na URL: `https://docs.google.com/spreadsheets/d/ESTE_É_O_ID/edit`)
3. Compartilhe a planilha com o e-mail da service account (campo `client_email` dentro do JSON baixado), com permissão de **Editor**
4. As abas (usuários, tarefas, categorias, etc.) e cabeçalhos são criados automaticamente na primeira execução

### 3. Configurar variáveis de ambiente no Vercel
No painel do projeto no Vercel ("Settings" → "Environment Variables"), adicione:

| Variável | Valor |
|---|---|
| `SECRET_KEY` | qualquer texto secreto aleatório |
| `GOOGLE_SHEET_ID` | o ID copiado da URL da planilha |
| `GOOGLE_CREDENTIALS_JSON` | o conteúdo inteiro do arquivo JSON da service account, em uma linha só |

### 4. Importar o repositório no Vercel
No painel do Vercel: "Add New..." → "Project" → selecione o repositório `sedra-gut` → Deploy.
O arquivo `vercel.json` já configura o build do Python/Flask automaticamente.

### ⚠️ Limitação conhecida: upload de logo
A tela de Aparência permite enviar uma logo da empresa. No Vercel, o sistema de arquivos
é somente leitura fora da pasta `/tmp`, e `/tmp` **não persiste** entre execuções (a cada
"cold start" o arquivo enviado é perdido). O upload funciona sem erro, mas a logo pode
sumir depois de um tempo. Para resolver de forma definitiva seria necessário um serviço
de armazenamento externo (ex: Vercel Blob, Cloudinary, S3) — fora do escopo desta migração.

---

## 🔐 Segurança
- As senhas são **criptografadas** antes de salvar no banco (nunca salvas em texto puro)
- A sessão de login expira quando o navegador é fechado
- Para uso em produção (internet pública), consulte as instruções da V2

---

## 🗺️ Roadmap — Próximas versões

| Versão | Funcionalidades Planejadas |
|--------|---------------------------|
| V1.0626 | ✅ Matriz GUT, Login, Cadastro, Histórico de atividades |
| V2 | Integração Gmail, Drive e Google Agenda |
| V3 | Relatórios em PDF, gráficos de progresso |
| V4 | Notificações por e-mail automáticas |
| V5 | Dashboard executivo com indicadores |

---

## ❓ Problemas comuns

**"python não é reconhecido como comando"**
→ Instale o Python em python.org e marque "Add Python to PATH"

**"ModuleNotFoundError: No module named 'flask'"**
→ Rode novamente: `pip install -r requirements.txt`

**Página não abre no navegador**
→ Confirme que o terminal está mostrando "Running on http://..." e acesse o endereço exato

---

*SEDRA Consultoria — Sistema interno de gestão*
