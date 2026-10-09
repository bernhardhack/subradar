/* SubRadar app — vanilla JS, no build step. */
(() => {
  "use strict";

  const STORE_KEY = "subradar.v1";
  const INKS = [
    ["#0078BF", "#FF48B0"],
    ["#000000", "#FFE800"],
    ["#00838A", "#FF48B0"],
    ["#000000", "#FF48B0"],
    ["#0078BF", "#FFE800"],
  ];
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // ---------- state ----------
  const state = { data: null, events: [], view: "weekend", base: "wien", swipes: {}, undo: [] };

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
      state.base = raw.base === "brunnbach" ? "brunnbach" : "wien";
      state.swipes = raw.swipes && typeof raw.swipes === "object" ? raw.swipes : {};
    } catch { /* private mode or blocked storage: run without memory */ }
  }
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify({ base: state.base, swipes: state.swipes })); } catch { /* ignore */ }
  }

  // ---------- helpers ----------
  const hash = (s) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const inksFor = (ev) => INKS[hash(ev.id) % INKS.length];
  const tiltFor = (ev) => ((hash(ev.id + "t") % 33) - 16) / 10; // -1.6..1.6 deg
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const dWeek = new Intl.DateTimeFormat("de-AT", { weekday: "short" });
  const dLong = new Intl.DateTimeFormat("de-AT", { weekday: "long", day: "numeric", month: "long" });
  const dDay = new Intl.DateTimeFormat("de-AT", { day: "numeric", month: "numeric" });
  const dTime = new Intl.DateTimeFormat("de-AT", { hour: "2-digit", minute: "2-digit" });
  const dMonth = new Intl.DateTimeFormat("de-AT", { month: "long" });
  const weekday = (d) => dWeek.format(d).replace(".", "");
  const timeOf = (ev) => (ev.all_day ? "ganztags" : dTime.format(new Date(ev.start)));
  const baseName = () => (state.data?.bases || {})[state.base] || state.base;

  function travelText(ev) {
    const m = ev.travel?.[state.base];
    if (m == null) return null;
    if (m === 0) return ["vor Ort", ""];
    if (m < 90) return [`${m} min`, `von ${baseName()}`];
    const h = Math.floor(m / 60), r = Math.round((m % 60) / 15) * 15;
    return [r ? `${h} h ${r}` : `${h} h`, `von ${baseName()}`];
  }

  function adjusted(ev) {
    const m = ev.travel?.[state.base] ?? 60;
    return (ev.score ?? 4) - Math.max(0, m - 45) / 30 + (ev.advance ? 0.5 : 0);
  }

  function weekendRange(now = new Date()) {
    const d = new Date(now); d.setHours(0, 0, 0, 0);
    const day = d.getDay(); // 0 Sun .. 6 Sat
    const back = { 5: 0, 6: 1, 0: 2 }[day];
    const fri = new Date(d);
    if (back !== undefined) fri.setDate(d.getDate() - back);
    else fri.setDate(d.getDate() + ((5 - day + 7) % 7));
    const mon = new Date(fri); mon.setDate(fri.getDate() + 3);
    return [fri, mon];
  }

  function upcoming() {
    const now = Date.now();
    return state.events.filter((ev) => {
      const end = ev.end ? Date.parse(ev.end) : Date.parse(ev.start) + 3 * 3600e3;
      return end >= now;
    });
  }

  function listFor(view) {
    const [fri, mon] = weekendRange();
    const evs = upcoming();
    if (view === "weekend") return evs.filter((e) => Date.parse(e.start) < mon.getTime() && (Date.parse(e.end || e.start) >= fri.getTime()));
    if (view === "later") return evs.filter((e) => Date.parse(e.start) >= mon.getTime());
    return evs;
  }

  function deckItems() {
    return listFor(state.view)
      .filter((e) => !state.swipes[e.id])
      .sort((a, b) => (state.view === "later" ? Number(!!b.advance) - Number(!!a.advance) : 0) || adjusted(b) - adjusted(a));
  }

  // ---------- poster ----------
  function posterHTML(ev) {
    const d = new Date(ev.start);
    const tr = travelText(ev);
    const tags = (ev.tags || []).join(" / ");
    const img = ev.image ? `<div class="p-img"><img src="${esc(ev.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.remove()"></div>` : "";
    return `
      <div class="p-head">
        <div class="p-when">${esc(weekday(d))} ${esc(timeOf(ev))}<small>${esc(dLong.format(d))}</small></div>
        ${tr ? `<div class="sticker">${esc(tr[0])}<small>${esc(tr[1])}</small></div>` : ""}
      </div>
      <div class="p-art">${img}<h2 class="p-title" data-text="${esc(ev.title)}"><span>${esc(ev.title)}</span></h2></div>
      <div class="p-foot">
        ${ev.why ? `<p class="p-why">${esc(ev.why)}</p>` : ""}
        <p class="p-meta">${esc(ev.venue)}${ev.city && ev.city !== ev.venue ? `, ${esc(ev.city)}` : ""}</p>
        ${tags ? `<p class="p-tags">${esc(tags)}</p>` : ""}
      </div>
      ${ev.advance ? `<div class="flag">Früh buchen</div>` : ""}
      <div class="stamp stamp-yes" aria-hidden="true">hin!</div>
      <div class="stamp stamp-no" aria-hidden="true">nö</div>`;
  }

  function fitTitle(el) {
    const box = el.parentElement;
    const len = el.textContent.length;
    let fs = len <= 10 ? 128 : len <= 20 ? 100 : len <= 34 ? 78 : 60;
    const maxH = box.clientHeight;
    for (let round = 0; round < 10; round++) {
      el.style.setProperty("--fs", fs + "px");
      for (const wd of [130, 115, 100, 88, 76, 64, 55]) {
        el.style.setProperty("--wd", wd);
        if (el.scrollWidth <= el.clientWidth + 5 && el.offsetHeight <= maxH) return; // +5: overprint offset
      }
      fs *= 0.9;
    }
  }

  // ---------- deck ----------
  const deckEl = $("[data-deck]");

  function renderDeck() {
    const items = deckItems();
    deckEl.innerHTML = "";
    $("[data-act=undo]").disabled = state.undo.length === 0;
    $$("[data-act=yes],[data-act=no]").forEach((b) => (b.disabled = items.length === 0));
    if (!items.length) {
      const saved = savedEvents().length;
      const other = state.view === "weekend" ? "later" : "weekend";
      deckEl.innerHTML = `<div class="empty">
        <p>${state.view === "weekend" ? "Fürs Wochenende hast du alles gesehen." : "Mehr ist gerade nicht in Sicht."}</p>
        ${saved ? `<button type="button" class="tool" data-goto="saved">Gemerkt ansehen (${saved})</button>` : ""}
        <button type="button" class="tool" data-goto="${other}">${other === "later" ? "Spätere Termine durchsehen" : "Zurück zum Wochenende"}</button>
      </div>`;
      return;
    }
    items.slice(0, 3).reverse().forEach((ev, i, arr) => {
      const depth = arr.length - 1 - i;
      const [c1, c2] = inksFor(ev);
      const card = document.createElement("article");
      card.className = "poster" + (depth === 1 ? " is-under" : depth === 2 ? " is-under2" : "");
      card.style.setProperty("--c1", c1);
      card.style.setProperty("--c2", c2);
      card.style.setProperty("--tilt", tiltFor(ev) + "deg");
      card.dataset.id = ev.id;
      card.innerHTML = posterHTML(ev);
      if (depth === 0) {
        card.tabIndex = 0;
        card.setAttribute("aria-label", `${ev.title}, ${dLong.format(new Date(ev.start))}, ${ev.venue}. Pfeil rechts merken, Pfeil links überspringen, Enter für Details.`);
        attachDrag(card, ev);
      } else {
        card.setAttribute("aria-hidden", "true");
      }
      deckEl.appendChild(card);
      fitTitle($(".p-title", card));
    });
  }

  function topCard() { return deckEl.querySelector(".poster:last-of-type"); }

  function decide(verdict, card = topCard()) {
    if (!card || card.classList.contains("fly")) return;
    const ev = state.events.find((e) => e.id === card.dataset.id);
    if (!ev) return;
    state.swipes[ev.id] = {
      verdict, at: new Date().toISOString(), title: ev.title, venue: ev.venue, city: ev.city,
      tags: ev.tags || [], start: ev.start, score: ev.score,
    };
    state.undo.push(ev.id);
    save();
    navigator.vibrate?.(8);
    const dir = verdict === "yes" ? 1 : -1;
    $(".stamp-" + verdict, card).style.opacity = 1;
    card.classList.remove("dragging", "settle");
    card.classList.add("fly");
    card.style.transform = `translate(${dir * 140}%, 30px) rotate(${dir * 22}deg)`;
    setTimeout(() => { renderDeck(); renderCount(); if (state.view === "saved") renderSaved(); }, 300);
  }

  function undo() {
    const id = state.undo.pop();
    if (!id) return;
    delete state.swipes[id];
    save();
    const ev = state.events.find((e) => e.id === id);
    if (ev) {
      const [fri, mon] = weekendRange();
      const inWeekend = Date.parse(ev.start) < mon.getTime() && Date.parse(ev.end || ev.start) >= fri.getTime();
      if (state.view !== (inWeekend ? "weekend" : "later")) setView(inWeekend ? "weekend" : "later");
    }
    renderDeck(); renderCount();
    topCard()?.focus();
  }

  function attachDrag(card, ev) {
    let x0 = 0, y0 = 0, t0 = 0, dx = 0, dy = 0, active = false;
    const yes = $(".stamp-yes", card), no = $(".stamp-no", card);
    const tilt = tiltFor(ev);

    card.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("a,button")) return;
      active = true; x0 = e.clientX; y0 = e.clientY; t0 = performance.now(); dx = dy = 0;
      card.setPointerCapture(e.pointerId);
      card.classList.add("dragging"); card.classList.remove("settle");
    });
    card.addEventListener("pointermove", (e) => {
      if (!active) return;
      dx = e.clientX - x0; dy = e.clientY - y0;
      card.style.transform = `translate(${dx}px, ${dy * 0.25}px) rotate(${tilt + dx / 16}deg)`;
      const p = Math.min(1, Math.abs(dx) / 110);
      yes.style.opacity = dx > 0 ? p : 0;
      no.style.opacity = dx < 0 ? p : 0;
    });
    const end = () => {
      if (!active) return;
      active = false;
      const dt = performance.now() - t0;
      const v = Math.abs(dx) / Math.max(dt, 1);
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6 && dt < 350) {
        card.classList.remove("dragging");
        card.style.transform = "";
        openSheet(ev);
        return;
      }
      if (Math.abs(dx) > card.clientWidth * 0.28 || (v > 0.6 && Math.abs(dx) > 30)) {
        decide(dx > 0 ? "yes" : "no", card);
      } else {
        card.classList.remove("dragging"); card.classList.add("settle");
        card.style.transform = ""; yes.style.opacity = 0; no.style.opacity = 0;
      }
    };
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openSheet(ev); }
    });
  }

  // ---------- detail sheet ----------
  const sheet = $("[data-sheet]");
  function openSheet(ev) {
    const d = new Date(ev.start);
    const [c1] = inksFor(ev);
    const tr = travelText(ev);
    $("[data-sheet-body]").innerHTML = `
      <h2 id="sheet-title" style="--c1:${c1}">${esc(ev.title)}</h2>
      <p class="s-meta">${esc(dLong.format(d))}, ${esc(timeOf(ev))}<br>${esc(ev.venue)}${ev.city !== ev.venue ? ", " + esc(ev.city) : ""}${tr ? `, ${esc(tr[0])} ${esc(tr[1])}` : ""}</p>
      ${ev.why ? `<p class="s-why">${esc(ev.why)}</p>` : ""}
      ${ev.description ? `<p class="s-desc">${esc(ev.description)}</p>` : ""}
      <div class="s-links">
        ${ev.url ? `<a class="primary" href="${esc(ev.url)}" target="_blank" rel="noopener">Zur Seite des Veranstalters</a>` : ""}
        <a href="${esc(ev.gcal)}" target="_blank" rel="noopener">In Google Kalender eintragen</a>
        <a href="${esc(ev.ics)}" download>Kalenderdatei laden (.ics)</a>
        ${navigator.share ? `<button type="button" data-share>Teilen</button>` : ""}
      </div>`;
    const shareBtn = $("[data-share]", sheet);
    shareBtn?.addEventListener("click", () => {
      navigator.share({ title: ev.title, text: `${ev.title}, ${dLong.format(d)}, ${ev.venue}`, url: ev.url }).catch(() => {});
    });
    sheet.showModal();
  }
  $("[data-close]").addEventListener("click", () => sheet.close());
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });

  // ---------- saved ----------
  function savedEvents() {
    return upcoming().filter((e) => state.swipes[e.id]?.verdict === "yes").sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
  }

  function renderSaved() {
    const list = $("[data-saved-list]");
    const evs = savedEvents();
    if (!evs.length) {
      list.innerHTML = `<p class="saved-empty">Noch nichts gemerkt. Wisch ein Plakat nach rechts, dann landet es hier.</p>`;
      return;
    }
    let html = "", lastDay = "";
    for (const ev of evs) {
      const d = new Date(ev.start);
      const dayKey = d.toDateString();
      if (dayKey !== lastDay) { html += `<h3 class="day-h">${esc(dLong.format(d))}</h3>`; lastDay = dayKey; }
      const tr = travelText(ev);
      html += `<div class="row" style="--c1:${inksFor(ev)[0]}">
        <div class="row-time">${esc(timeOf(ev))}</div>
        <p class="row-title">${esc(ev.title)}</p>
        <p class="row-meta">${esc(ev.venue)}${ev.city !== ev.venue ? ", " + esc(ev.city) : ""}${tr ? `, ${esc(tr[0])} ${esc(tr[1])}` : ""}</p>
        <div class="row-links">
          ${ev.url ? `<a href="${esc(ev.url)}" target="_blank" rel="noopener">Veranstalter</a>` : ""}
          <a href="${esc(ev.gcal)}" target="_blank" rel="noopener">Google Kalender</a>
          <a href="${esc(ev.ics)}" download>.ics</a>
          <button type="button" data-unsave="${esc(ev.id)}">Entfernen</button>
        </div>
      </div>`;
    }
    list.innerHTML = html;
  }

  function renderCount() {
    const n = savedEvents().length;
    $("[data-count]").textContent = n ? String(n) : "";
  }

  // ---------- views ----------
  function setView(view) {
    state.view = view;
    $$("[role=tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === view)));
    const isSaved = view === "saved";
    $("[data-panel=deck]").hidden = isSaved;
    $("[data-panel=saved]").hidden = !isSaved;
    if (isSaved) renderSaved();
    else { renderRange(); renderDeck(); }
  }

  function renderRange() {
    const [fri, mon] = weekendRange();
    const sun = new Date(mon); sun.setDate(mon.getDate() - 1);
    const txt = state.view === "weekend"
      ? `Freitag ${dDay.format(fri)} bis Sonntag ${dDay.format(sun)}, sortiert für ${baseName()}`
      : `Ab ${dDay.format(mon)}, die nächsten Wochen. Früh-buchen-Tipps zuerst.`;
    $("[data-range]").textContent = txt;
  }

  function setBase(base) {
    state.base = base;
    save();
    $$("[data-base]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === base)));
    if (state.view === "saved") renderSaved(); else { renderRange(); renderDeck(); }
  }

  function renderFoot() {
    const d = state.data;
    if (!d) return;
    const when = new Date(d.generated);
    const src = (d.sources || []).map((s) =>
      `<li>${esc(s.name)}: ${s.ok ? `${s.count} Termine (${esc(s.method)})` : esc(s.error || s.method || "nichts gefunden")}</li>`).join("");
    $("[data-foot]").innerHTML = `Stand ${esc(dDay.format(when))} ${esc(dTime.format(when))}${d.scoring === "keywords" ? ", Bewertung nur nach Stichworten" : ""}.
      ${src ? `<details><summary>Quellen</summary><ul>${src}</ul></details>` : ""}`;
  }

  function exportSwipes() {
    const payload = { version: 1, exported: new Date().toISOString(), swipes: Object.entries(state.swipes).map(([id, s]) => ({ id, ...s })) };
    const blob = new Blob([JSON.stringify(payload, null, 1)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: "swipes.json" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ---------- wiring ----------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("button, a");
    if (!t) return;
    if (t.dataset.act === "yes") decide("yes");
    else if (t.dataset.act === "no") decide("no");
    else if (t.dataset.act === "undo") undo();
    else if (t.dataset.view) setView(t.dataset.view);
    else if (t.dataset.goto) setView(t.dataset.goto);
    else if (t.dataset.base) setBase(t.dataset.base);
    else if (t.dataset.unsave) { delete state.swipes[t.dataset.unsave]; save(); renderSaved(); renderCount(); }
    else if (t.hasAttribute("data-export")) exportSwipes();
  });

  document.addEventListener("keydown", (e) => {
    if (sheet.open || state.view === "saved" || e.target.closest("input,textarea")) return;
    if (e.key === "ArrowRight") { e.preventDefault(); decide("yes"); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); decide("no"); }
    else if (e.key === "Backspace" || e.key === "z") { e.preventDefault(); undo(); }
  });

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => $$(".p-title", deckEl).forEach(fitTitle), 150);
  });

  async function init() {
    load();
    $$("[data-base]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.base === state.base)));
    const sub = $("[data-subscribe]");
    if (location.protocol === "https:") sub.href = new URL("radar.ics", location.href).href.replace(/^https:/, "webcal:");
    try {
      const res = await fetch("data/events.json", { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.data = await res.json();
      state.events = state.data.events || [];
    } catch (err) {
      deckEl.innerHTML = `<div class="empty"><p>Die Termine konnten nicht geladen werden (${esc(err.message)}). Seite neu laden oder später nochmal versuchen.</p></div>`;
      return;
    }
    $(".sample").hidden = !state.data.sample;
    renderFoot(); renderCount();
    if (document.fonts?.ready) await document.fonts.ready;
    setView("weekend");
  }
  init();
})();
