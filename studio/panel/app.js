/* Garment Studio panel: talks to studio/server.py only. */
const $ = (id) => document.getElementById(id);
const state = { jobs: [], current: null, dirty: false, timer: null };

const STAGE_LABEL = {
  created: "待描述", described: "待确认", approved: "已确认",
  designed: "已出 JSON", packaged: "已生成 3D", simulated: "已仿真", failed: "失败",
};

function toast(msg, ms = 2200) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data.error || res.status + " " + res.statusText);
  return data;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) +
         " " + p(d.getHours()) + ":" + p(d.getMinutes());
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/* ------------------------------------------------------------ job list */
function renderList() {
  const box = $("joblist");
  box.textContent = "";
  if (!state.jobs.length) {
    box.append(el("div", "empty-list", "还没有作业"));
    return;
  }
  for (const job of state.jobs) {
    const item = el("div", "job-item" + (job.job_id === state.current ? " active" : ""));
    item.append(el("div", "t", job.title || "未命名款式"));
    const s = el("div", "s");
    s.append(el("span", "badge " + job.stage, STAGE_LABEL[job.stage] || job.stage));
    s.append(el("span", null, fmtTime(job.created_at)));
    item.append(s);
    item.onclick = () => selectJob(job.job_id);
    box.append(item);
  }
}

/* ------------------------------------------------------------- detail */
function renderArtifacts(job) {
  const box = $("artifacts");
  box.textContent = "";
  const add = (caption, src, opts = {}) => {
    const card = el("div", "art");
    if (src) {
      const a = el("a");
      a.href = src;
      a.target = "_blank";
      a.rel = "noopener";
      const img = el("img");
      img.src = src;
      img.loading = "lazy";
      img.alt = caption;
      a.append(img);
      card.append(a);
    } else {
      card.append(el("div", "missing", opts.missing || "暂无"));
    }
    const cap = el("div", "cap");
    cap.append(el("span", null, caption));
    if (opts.extra) cap.append(el("span", null, opts.extra));
    card.append(cap);
    box.append(card);
  };
  const base = "/files/" + job.job_id + "/";
  // re-running a job overwrites the pngs under the same URL, so tag them with the job's
  // mtime: otherwise the browser keeps showing the previous drape after a re-run
  const ver = job.mtime ? "?v=" + encodeURIComponent(job.mtime) : "";
  if (job.images.pattern) add("2D 纸样", base + job.images.pattern + ver);
  if (job.images.preview) add("网格预览", base + job.images.preview + ver);
  if (job.images.sim) add("布料仿真", base + job.images.sim + ver);
  if (job.sim && job.sim.glb) {
    const card = el("div", "art");
    const link = el("a", null, "下载 sim.glb");
    link.href = base + "sim/sim.glb";
    link.target = "_blank";
    link.rel = "noopener";
    const holder = el("div", "missing");
    holder.append(link);
    if (job.images.blend) {
      const blend = el("a", null, "下载 .blend 工程");
      blend.href = base + job.images.blend;
      blend.target = "_blank";
      blend.rel = "noopener";
      blend.style.marginLeft = "10px";
      holder.append(blend);
    }
    card.append(holder);
    const cap = el("div", "cap");
    cap.append(el("span", null, "3D 模型"));
    card.append(cap);
    box.append(card);
  }
  if (!box.children.length) box.append(el("div", "missing", "还没有产物"));
}

function renderDetail(job) {
  $("empty").hidden = true;
  $("detail").hidden = false;
  $("job-title").textContent = job.title || "未命名款式";
  const badge = $("job-stage");
  badge.className = "badge " + job.stage;
  badge.textContent = STAGE_LABEL[job.stage] || job.stage;
  $("job-time").textContent = fmtTime(job.created_at);
  $("job-id").textContent = job.job_id;

  const wrap = $("input-wrap");
  wrap.textContent = "";
  if (job.image) {
    const img = el("img");
    img.src = "/files/" + job.job_id + "/" + job.image +
      (job.mtime ? "?v=" + encodeURIComponent(job.mtime) : "");
    wrap.append(img);
  } else {
    wrap.append(el("div", "noimg", "没有输入图"));
  }
  $("job-notes").textContent = job.notes || "";

  const textarea = $("desc");
  if (document.activeElement !== textarea && textarea.value !== (job.description || "")) {
    if (!state.dirty) textarea.value = job.description || "";
  }
  if (!textarea.value && job.description) textarea.value = job.description;

  const ap = job.approval;
  if (ap && ap.decision === "accept") {
    $("approval-state").textContent = "已确认 · " + fmtTime(ap.ts);
  } else if (ap && ap.decision === "edit") {
    $("approval-state").textContent = "已按修改确认 · " + fmtTime(ap.ts);
  } else if (job.description) {
    $("approval-state").textContent = "等待你确认";
  } else {
    $("approval-state").textContent = "等待模型写描述";
  }

  const notice = $("notice");
  const res = job.result || {};
  const lines = [];
  if (res.error && res.error.message) lines.push("失败：" + res.error.message);
  for (const w of res.warnings || []) lines.push("注意：" + w);
  if (lines.length) {
    notice.textContent = lines.join("\n");
    notice.classList.toggle("error", Boolean(res.error && res.error.message));
    notice.hidden = false;
  } else {
    notice.hidden = true;
  }

  $("log").textContent = job.log_tail || "（无日志）";
  renderArtifacts(job);
  renderList();
  $("open-folder").dataset.job = job.job_id;
}

/* ------------------------------------------------------------- actions */
async function selectJob(jobId) {
  state.current = jobId;
  state.dirty = false;
  renderList();
  try {
    const job = await api("/api/jobs/" + jobId);
    renderDetail(job);
  } catch (e) { toast("读取失败: " + e.message); }
}

async function submitApproval(decision) {
  const jobId = state.current;
  if (!jobId) return;
  const text = $("desc").value;
  try {
    await api("/api/jobs/" + jobId + "/approval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, text }),
    });
    state.dirty = false;
    toast(decision === "accept" ? "已确认，等待模型生成 JSON" : "已把修改发回模型");
    await selectJob(jobId);
  } catch (e) { toast("提交失败: " + e.message); }
}

async function refresh() {
  try {
    const data = await api("/api/jobs");
    state.jobs = data.jobs || [];
    $("server-state").textContent = "服务已连接 · " + state.jobs.length + " 个作业";
    if (!state.current && state.jobs.length) return selectJob(state.jobs[0].job_id);
    if (state.current) {
      const job = state.jobs.find((j) => j.job_id === state.current);
      if (job) return renderDetail(await api("/api/jobs/" + state.current));
    }
    renderList();
    $("empty").hidden = state.jobs.length > 0;
    $("detail").hidden = state.jobs.length === 0;
  } catch (e) {
    $("server-state").textContent = "服务未连接";
  }
}

$("refresh").onclick = refresh;
$("btn-accept").onclick = () => submitApproval("accept");
$("btn-edit").onclick = () => submitApproval("edit");
$("desc").addEventListener("input", () => { state.dirty = true; });
$("open-folder").onclick = async () => {
  const jobId = $("open-folder").dataset.job;
  if (!jobId) return;
  const btn = $("open-folder");
  btn.disabled = true;
  try {
    const r = await api("/api/jobs/" + jobId + "/open", { method: "POST" });
    if (r && r.ok) {
      toast("已在资源管理器打开：" + r.path, 4000);
    } else {
      // 面板服务多半是被沙箱 shell 启动的（没有可用 window station），自己开不了窗口。
      // 如果面板嵌在 DSH 里，就让宿主进程去开（它有真实桌面会话）。
      if (window.parent !== window) toast("服务端开不了窗口，正在请 DSH 代开…", 2500);
      const viaHost = await revealViaHost(jobId);
      if (viaHost && viaHost.ok) {
        toast("已打开：" + viaHost.path, 4000);
      } else {
        const why = (r && r.error) || (viaHost && viaHost.error) || "未知原因";
        await copyText((r && r.path) || "");
        toast("系统没能打开窗口（" + why + "）。路径已复制，粘贴到资源管理器地址栏即可。", 9000);
      }
    }
  } catch (e) {
    toast("打开文件夹失败：" + e.message, 6000);
  } finally {
    btn.disabled = false;
  }
};

/** 请 DSH 宿主进程帮忙打开文件夹（跨源：走 postMessage，宿主页面再 fetch 路由）。 */
function revealViaHost(jobId) {
  return new Promise((resolve) => {
    if (window.parent === window) return resolve(null);
    let done = false;
    const timer = setTimeout(() => { if (!done) { done = true; cleanup(); resolve(null); } }, 3500);
    function onMsg(ev) {
      const d = ev.data || {};
      if (d.type !== "gcstudio-reveal-result" || d.job !== jobId) return;
      done = true; cleanup(); resolve(d);
    }
    function cleanup() { clearTimeout(timer); window.removeEventListener("message", onMsg); }
    window.addEventListener("message", onMsg);
    try { window.parent.postMessage({ type: "gcstudio-reveal", job: jobId }, "*"); }
    catch (e) { done = true; cleanup(); resolve(null); }
  });
}

async function copyText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { /* fall through to the textarea trick */ }
  try {
    const ta = el("textarea", null, text);
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch (e) { return false; }
}

refresh();
setInterval(() => { if (!state.dirty) refresh(); }, 2500);
