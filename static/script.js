/**
 * SEDRA GUT — Script V1.0626
 */

// ── Sidebar ────────────────────────────────────────────────
function toggleSidebar() {
    document.getElementById("sidebar")?.classList.toggle("collapsed");
}

// ── Modais ─────────────────────────────────────────────────
function abrirModal(id) {
    document.getElementById(id)?.classList.add("open");
}

function fecharModal(id) {
    document.getElementById(id)?.classList.remove("open");
}

document.addEventListener("keydown", e => {
    if (e.key === "Escape")
        document.querySelectorAll(".modal-overlay.open")
                .forEach(m => m.classList.remove("open"));
});

function abrirModalNova() { abrirModal("modal-nova"); }

async function abrirModalEditar(id) {
    try {
        const r = await fetch(`/tarefa/${id}/editar`);
        const t = await r.json();

        document.getElementById("edit-titulo").value      = t.titulo;
        document.getElementById("edit-descricao").value   = t.descricao || "";
        document.getElementById("edit-responsavel").value = t.responsavel || "";
        document.getElementById("edit-categoria").value   = t.categoria;
        document.getElementById("edit-prazo").value       = t.prazo || "";

        const editStatus = document.getElementById("edit-status");
        if (editStatus) editStatus.value = t.status;

        document.getElementById("form-editar").action = `/tarefa/${id}/editar`;

        const container = document.getElementById("edit-gut-inputs");
        ["gravidade","urgencia","tendencia"].forEach(campo => {
            selecionarNota(container, campo, t[campo]);
        });
        atualizarPreview("editar");

        // Resetar abas para "Editar" ao abrir
        document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.modal-tab')[0].classList.add('active');
        document.getElementById('aba-editar').style.display = '';
        document.getElementById('aba-historico').style.display = 'none';

        // Preencher histórico
        const lista = document.getElementById('historico-lista');
        if (t.historico && t.historico.length > 0) {
            lista.innerHTML = t.historico.map(h => `
                <div class="historico-item">
                    <div class="historico-avatar">${h.usuario.substring(0,2).toUpperCase()}</div>
                    <div>
                        <div class="historico-desc">${h.descricao}</div>
                        <div class="historico-meta">${h.usuario} · ${h.data}</div>
                    </div>
                </div>`).join('');
        } else {
            lista.innerHTML = '<div class="historico-vazio">Nenhuma movimentação registrada ainda.</div>';
        }

        abrirModal("modal-editar");
    } catch(e) {
        alert("Erro ao carregar tarefa."); console.error(e);
    }
}

// ── Seletor de notas GUT ────────────────────────────────────
function selecionarNota(container, nome, valor) {
    const sel = container?.querySelector(`.nota-selector[data-name="${nome}"]`);
    if (!sel) return;
    sel.querySelectorAll(".nota-btn").forEach(b => b.classList.remove("selected"));
    const btn = sel.querySelector(`.nota-btn[data-val="${valor}"]`);
    if (btn) {
        btn.classList.add("selected");
        const form = sel.closest("form") || sel.closest(".modal-box");
        form?.querySelector(`input[name="${nome}"]`)?.setAttribute("value", valor);
    }
}

function calcularNivel(gut) {
    if (gut >= 75) return ["Crítica","danger"];
    if (gut >= 40) return ["Alta","warning"];
    if (gut >= 15) return ["Média","info"];
    return ["Baixa","secondary"];
}

function atualizarPreview(modo) {
    const prefix = modo === "nova" ? "#modal-nova" : "#modal-editar";
    const g = parseInt(document.querySelector(`${prefix} input[name='gravidade']`)?.value || 1);
    const u = parseInt(document.querySelector(`${prefix} input[name='urgencia']`)?.value  || 1);
    const t = parseInt(document.querySelector(`${prefix} input[name='tendencia']`)?.value || 1);
    const gut = g * u * t;

    const sufixo = modo === "nova" ? "valor" : "editar";
    const elemVal   = document.getElementById(`gut-preview-${sufixo}`);
    const elemNivel = document.getElementById(modo === "nova" ? "gut-preview-nivel" : "gut-nivel-editar");

    if (elemVal) elemVal.textContent = gut;
    if (elemNivel) {
        const [texto, cor] = calcularNivel(gut);
        elemNivel.textContent = texto;
        elemNivel.className   = `badge badge-${cor}`;
    }
}

function inicializarSeletores() {
    document.querySelectorAll(".nota-btn").forEach(btn => {
        btn.addEventListener("click", function() {
            const sel  = this.closest(".nota-selector");
            const nome = sel.dataset.name;
            const val  = parseInt(this.dataset.val);

            sel.querySelectorAll(".nota-btn").forEach(b => b.classList.remove("selected"));
            this.classList.add("selected");

            const form = this.closest("form") || this.closest(".modal-box");
            if (form) {
                const h = form.querySelector(`input[name="${nome}"]`);
                if (h) h.value = val;
            }

            const novaAberta   = document.getElementById("modal-nova")?.classList.contains("open");
            const editarAberta = document.getElementById("modal-editar")?.classList.contains("open");
            if (novaAberta)   atualizarPreview("nova");
            if (editarAberta) atualizarPreview("editar");
        });
    });
}

// ── Filtros da tabela ───────────────────────────────────────
function filtrarTabela() {
    const status    = document.getElementById("filtro-status")?.value.toLowerCase()    || "";
    const categoria = document.getElementById("filtro-categoria")?.value.toLowerCase() || "";
    const busca     = document.getElementById("filtro-busca")?.value.toLowerCase()     || "";

    document.querySelectorAll(".tarefa-row").forEach(row => {
        const ok = (!status    || row.dataset.status?.toLowerCase().includes(status))    &&
                   (!categoria || row.dataset.categoria?.toLowerCase().includes(categoria)) &&
                   (!busca     || row.textContent.toLowerCase().includes(busca));
        row.style.display = ok ? "" : "none";
    });
}

// ── Init ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    inicializarSeletores();
    setTimeout(() => {
        document.querySelectorAll(".alert").forEach(a => {
            a.style.transition = "opacity 0.5s";
            a.style.opacity = "0";
            setTimeout(() => a.remove(), 500);
        });
    }, 5000);
});
