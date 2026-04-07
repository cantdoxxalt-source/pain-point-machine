#!/usr/bin/env python3
"""
Pain Point Machine — Web Dashboard with Live Activity Sidebar

Run: python dashboard.py
Open: http://localhost:5000
"""

import json
import os
import time
import queue
import threading
from datetime import datetime, timezone

from flask import Flask, render_template_string, jsonify, request, redirect, url_for, Response
from agents.store import Store
from agents.config import DEFAULT_SUBREDDIT, ANTHROPIC_API_KEY

app = Flask(__name__)
store = Store()

if not store.get_subreddits():
    store.add_subreddit(DEFAULT_SUBREDDIT)

# ---------------------------------------------------------------------------
# Live activity feed (thread-safe queue for SSE)
# ---------------------------------------------------------------------------
activity_log: list[dict] = []
sse_clients: list[queue.Queue] = []
pipeline_running = False

def emit(event_type: str, msg: str, data: dict = None):
    """Push an event to all connected SSE clients and the activity log."""
    entry = {
        "type": event_type,  # scan, qualify, draft, lead, pain, error, done, info
        "msg": msg,
        "data": data or {},
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    activity_log.append(entry)
    if len(activity_log) > 100:
        activity_log.pop(0)

    dead = []
    for q in sse_clients:
        try:
            q.put_nowait(entry)
        except queue.Full:
            dead.append(q)
    for q in dead:
        sse_clients.remove(q)


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pain Point Machine</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f0f; color: #e0e0e0; }

        /* Layout with sidebar */
        .app-layout { display: flex; height: 100vh; overflow: hidden; }
        .main-panel { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
        .main-scroll { flex: 1; overflow-y: auto; }

        /* Sidebar */
        .sidebar { width: 340px; background: #111; border-left: 1px solid #1f1f1f; display: flex; flex-direction: column; flex-shrink: 0; }
        .sidebar-header { padding: 16px; border-bottom: 1px solid #1f1f1f; display: flex; justify-content: space-between; align-items: center; }
        .sidebar-header h3 { font-size: 13px; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        .sidebar-status { display: flex; align-items: center; gap: 6px; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; }
        .status-dot.idle { background: #555; }
        .status-dot.running { background: #4ade80; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .status-label { font-size: 11px; color: #666; }

        .sidebar-feed { flex: 1; overflow-y: auto; padding: 8px; }
        .feed-empty { text-align: center; padding: 40px 16px; color: #444; font-size: 13px; }

        .feed-item { padding: 10px 12px; margin-bottom: 4px; border-radius: 8px; background: #1a1a1a; border-left: 3px solid #333; font-size: 13px; line-height: 1.5; animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
        .feed-item .feed-time { font-size: 10px; color: #444; margin-bottom: 2px; }
        .feed-item .feed-msg { color: #bbb; }
        .feed-item .feed-detail { font-size: 11px; color: #666; margin-top: 4px; }

        .feed-item.type-scan { border-left-color: #3b82f6; }
        .feed-item.type-pain { border-left-color: #ff6b35; }
        .feed-item.type-qualify { border-left-color: #f59e0b; }
        .feed-item.type-lead { border-left-color: #4ade80; }
        .feed-item.type-draft { border-left-color: #a78bfa; }
        .feed-item.type-error { border-left-color: #ef4444; }
        .feed-item.type-done { border-left-color: #4ade80; background: #0a1a0a; }
        .feed-item.type-info { border-left-color: #555; }

        .feed-icon { margin-right: 6px; }

        /* Sidebar actions */
        .sidebar-actions { padding: 12px; border-top: 1px solid #1f1f1f; }
        .sidebar-actions .btn { width: 100%; text-align: center; margin-bottom: 6px; }
        .btn-pipeline { background: linear-gradient(135deg, #ff6b35, #f59e0b); color: #000; padding: 12px; font-size: 14px; }
        .btn-pipeline:hover { opacity: 0.9; }
        .btn-pipeline:disabled { opacity: 0.4; cursor: not-allowed; }

        /* Nav */
        .nav { background: #1a1a1a; border-bottom: 1px solid #2a2a2a; padding: 12px 24px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
        .nav h1 { font-size: 18px; color: #ff6b35; }
        .nav h1 span { color: #888; font-weight: 400; font-size: 13px; margin-left: 8px; }
        .nav-links { display: flex; gap: 4px; }
        .nav-links a { color: #888; text-decoration: none; padding: 6px 14px; border-radius: 8px; font-size: 13px; transition: all 0.2s; }
        .nav-links a:hover, .nav-links a.active { background: #2a2a2a; color: #fff; }

        .container { max-width: 1100px; margin: 0 auto; padding: 24px; }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }
        .stat-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 16px; }
        .stat-card .label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
        .stat-card .value { font-size: 28px; font-weight: 700; color: #ff6b35; }
        .stat-card .value.green { color: #4ade80; }
        .stat-card .value.blue { color: #60a5fa; }
        .stat-card .value.purple { color: #a78bfa; }

        .section { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; margin-bottom: 24px; overflow: hidden; }
        .section-header { padding: 14px 18px; border-bottom: 1px solid #2a2a2a; display: flex; justify-content: space-between; align-items: center; }
        .section-header h2 { font-size: 15px; color: #fff; }
        .section-header .badge { background: #ff6b35; color: #000; font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 99px; }
        .section-body { padding: 18px; }

        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 10px 14px; font-size: 10px; color: #666; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #2a2a2a; }
        td { padding: 10px 14px; font-size: 13px; border-bottom: 1px solid #1f1f1f; vertical-align: top; }
        tr:hover { background: #222; }

        .score-badge { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
        .score-high { background: #ff6b3520; color: #ff6b35; }
        .score-med { background: #f59e0b20; color: #f59e0b; }
        .score-low { background: #6b728020; color: #9ca3af; }
        .signal-tag { display: inline-block; background: #2a2a2a; color: #aaa; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 1px 2px; }
        .text-preview { color: #888; font-size: 12px; max-width: 350px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .author { color: #60a5fa; font-size: 13px; }
        .link { color: #666; font-size: 12px; text-decoration: none; }
        .link:hover { color: #ff6b35; }

        .msg-card { background: #111; border: 1px solid #2a2a2a; border-radius: 8px; padding: 14px; margin: 8px 14px 14px; }
        .msg-card .msg-meta { font-size: 11px; color: #666; margin-bottom: 8px; }
        .msg-card .msg-body { font-size: 13px; color: #ccc; line-height: 1.6; white-space: pre-wrap; }

        .status { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 11px; font-weight: 600; }
        .status-new { background: #3b82f620; color: #60a5fa; }

        .empty { text-align: center; padding: 50px 20px; color: #555; }
        .empty h3 { font-size: 16px; margin-bottom: 8px; color: #666; }
        .empty p { font-size: 13px; }
        .empty code { background: #2a2a2a; padding: 4px 8px; border-radius: 4px; color: #ff6b35; }

        .inline-form { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; }
        .inline-form input, .inline-form select { padding: 8px 12px; background: #111; border: 1px solid #333; border-radius: 8px; color: #fff; font-size: 13px; }
        .inline-form input:focus, .inline-form select:focus { border-color: #ff6b35; outline: none; }
        .inline-form input[type="text"] { flex: 1; min-width: 180px; }

        .btn { padding: 8px 16px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; text-decoration: none; display: inline-block; }
        .btn-primary { background: #ff6b35; color: #000; }
        .btn-primary:hover { background: #ff8c5a; }
        .btn-danger { background: #dc262620; color: #ef4444; border: 1px solid #dc262640; }
        .btn-danger:hover { background: #dc262640; }
        .btn-success { background: #16a34a20; color: #4ade80; border: 1px solid #16a34a40; }
        .btn-muted { background: #2a2a2a; color: #888; }
        .btn-muted:hover { background: #333; color: #fff; }

        .item-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1f1f1f; }
        .item-row:last-child { border-bottom: none; }
        .item-row .item-meta { font-size: 12px; color: #666; margin-left: 8px; }
        .item-row .item-actions { display: flex; gap: 6px; }

        .tier-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 8px; }
        .tier-3 { background: #dc262620; color: #ef4444; }
        .tier-2 { background: #f59e0b20; color: #f59e0b; }
        .tier-1 { background: #6b728020; color: #9ca3af; }
        .sub-badge { display: inline-block; background: #ff6b3515; color: #ff6b35; padding: 4px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; }
        .sub-disabled { opacity: 0.4; }

        .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } .sidebar { display: none; } }

        .flash { padding: 12px 20px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
        .flash-success { background: #16a34a20; color: #4ade80; border: 1px solid #16a34a40; }
        .flash-error { background: #dc262620; color: #ef4444; border: 1px solid #dc262640; }
        .flash-info { background: #3b82f620; color: #60a5fa; border: 1px solid #3b82f640; }
    </style>
</head>
<body>
<div class="app-layout">
    <!-- MAIN -->
    <div class="main-panel">
        <div class="nav">
            <h1>Pain Point Machine <span>v2.0</span></h1>
            <div class="nav-links">
                <a href="/" class="{{ 'active' if page == 'dashboard' else '' }}">Dashboard</a>
                <a href="/pain-points" class="{{ 'active' if page == 'pain_points' else '' }}">Pain Points</a>
                <a href="/leads" class="{{ 'active' if page == 'leads' else '' }}">Leads</a>
                <a href="/outbox" class="{{ 'active' if page == 'outbox' else '' }}">Outbox</a>
                <a href="/settings" class="{{ 'active' if page == 'settings' else '' }}">Settings</a>
            </div>
        </div>
        <div class="main-scroll">
        <div class="container">
        {% if flash %}
            <div class="flash flash-{{ flash.type }}">{{ flash.msg }}</div>
        {% endif %}

        {% if page == 'dashboard' %}
            <div class="stats-grid">
                <div class="stat-card"><div class="label">Pain Points</div><div class="value">{{ stats.total_pain_points }}</div></div>
                <div class="stat-card"><div class="label">Leads</div><div class="value green">{{ stats.total_leads }}</div></div>
                <div class="stat-card"><div class="label">Drafts</div><div class="value blue">{{ stats.total_drafts }}</div></div>
                <div class="stat-card"><div class="label">Sent</div><div class="value purple">{{ stats.total_sent }}</div></div>
                <div class="stat-card"><div class="label">Runs</div><div class="value">{{ stats.total_runs }}</div></div>
            </div>

            <div style="margin-bottom: 20px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                <span style="color: #666; font-size: 12px;">Tracking:</span>
                {% for s in subreddits %}
                    <span class="sub-badge {{ 'sub-disabled' if not s.enabled else '' }}">r/{{ s.name }}</span>
                {% endfor %}
                <a href="/settings" class="btn btn-muted" style="font-size: 11px; padding: 4px 10px;">+ Add</a>
            </div>

            <div class="section">
                <div class="section-header"><h2>Recent Pain Points</h2><span class="badge">{{ recent_pp | length }}</span></div>
                {% if recent_pp %}
                <table>
                    <tr><th>Score</th><th>Author</th><th>Text</th><th>Signals</th><th>Age</th></tr>
                    {% for pp in recent_pp[:10] %}
                    <tr>
                        <td><span class="score-badge {{ 'score-high' if pp.score >= 8 else 'score-med' if pp.score >= 4 else 'score-low' }}">{{ pp.score }}</span></td>
                        <td><span class="author">u/{{ pp.author }}</span></td>
                        <td><div class="text-preview">{{ pp.text[:100] }}</div></td>
                        <td>{% for s in (pp.matched_signals or [])[:3] %}<span class="signal-tag">{{ s }}</span>{% endfor %}</td>
                        <td style="color: #666; font-size: 12px;">{{ pp.age_days }}d</td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}
                <div class="empty"><h3>No pain points yet</h3><p>Click <b>Run Full Pipeline</b> in the sidebar</p></div>
                {% endif %}
            </div>

        {% elif page == 'pain_points' %}
            <div class="section">
                <div class="section-header"><h2>All Pain Points</h2><span class="badge">{{ items | length }}</span></div>
                {% if items %}
                <table>
                    <tr><th>Score</th><th>Type</th><th>Author</th><th>Text</th><th>Signals</th><th>Upvotes</th><th>Link</th></tr>
                    {% for pp in items %}
                    <tr>
                        <td><span class="score-badge {{ 'score-high' if pp.score >= 8 else 'score-med' if pp.score >= 4 else 'score-low' }}">{{ pp.score }}</span></td>
                        <td style="color: #666; font-size: 11px;">{{ 'cmt' if pp.is_comment else 'post' }}</td>
                        <td><span class="author">u/{{ pp.author }}</span></td>
                        <td><div class="text-preview">{{ pp.text[:120] }}</div></td>
                        <td>{% for s in (pp.matched_signals or [])[:4] %}<span class="signal-tag">{{ s }}</span>{% endfor %}</td>
                        <td style="color: #666;">{{ pp.upvotes }}</td>
                        <td><a class="link" href="{{ pp.source_url }}" target="_blank">open</a></td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}<div class="empty"><h3>No data</h3></div>{% endif %}
            </div>

        {% elif page == 'leads' %}
            <div class="section">
                <div class="section-header"><h2>Qualified Leads</h2><span class="badge">{{ items | length }}</span></div>
                {% if items %}
                <table>
                    <tr><th>Score</th><th>Author</th><th>Buy</th><th>Urg</th><th>Sol</th><th>Reasoning</th><th>Status</th></tr>
                    {% for l in items %}
                    <tr>
                        <td><span class="score-badge {{ 'score-high' if l.lead_score >= 7 else 'score-med' if l.lead_score >= 5 else 'score-low' }}">{{ l.lead_score }}</span></td>
                        <td><span class="author">u/{{ l.pp_author or '?' }}</span></td>
                        <td style="color: #4ade80;">{{ l.buy_intent }}</td>
                        <td style="color: #f59e0b;">{{ l.urgency }}</td>
                        <td style="color: #60a5fa;">{{ l.solvability }}</td>
                        <td><div class="text-preview">{{ l.reasoning[:100] if l.reasoning else '' }}</div></td>
                        <td><span class="status status-{{ l.status or 'new' }}">{{ l.status or 'new' }}</span></td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}<div class="empty"><h3>No leads yet</h3><p>Run the pipeline to qualify pain points</p></div>{% endif %}
            </div>

        {% elif page == 'outbox' %}
            <div class="section">
                <div class="section-header"><h2>Outreach Drafts</h2><span class="badge">{{ items | length }}</span></div>
                {% if items %}
                    {% for o in items %}
                    <div class="msg-card">
                        <div class="msg-meta">
                            To: <span class="author">u/{{ o.pp_author or '?' }}</span>
                            &middot; Score: {{ o.lead_score or '?' }}
                            &middot; {{ o.word_count or '?' }}w
                            &middot; <a class="link" href="{{ o.pp_url or '#' }}" target="_blank">source</a>
                        </div>
                        <div class="msg-body">{{ o.message }}</div>
                    </div>
                    {% endfor %}
                {% else %}<div class="empty"><h3>No drafts yet</h3></div>{% endif %}
            </div>

        {% elif page == 'settings' %}
            <div class="two-col">
                <div class="section">
                    <div class="section-header"><h2>Subreddits</h2><span class="badge">{{ subreddits | length }}</span></div>
                    <div class="section-body">
                        <form method="POST" action="/settings/add-subreddit" class="inline-form">
                            <input type="text" name="name" placeholder="tressless, alopecia, haircare" required>
                            <button type="submit" class="btn btn-primary">Add</button>
                        </form>
                        {% for s in subreddits %}
                        <div class="item-row">
                            <div><span class="sub-badge {{ 'sub-disabled' if not s.enabled else '' }}">r/{{ s.name }}</span>{% if not s.enabled %}<span class="item-meta">(paused)</span>{% endif %}</div>
                            <div class="item-actions">
                                <form method="POST" action="/settings/toggle-subreddit/{{ s.id }}" style="display:inline;"><button type="submit" class="btn {{ 'btn-muted' if s.enabled else 'btn-success' }}" style="font-size:11px;padding:4px 10px;">{{ 'Pause' if s.enabled else 'Enable' }}</button></form>
                                <form method="POST" action="/settings/remove-subreddit/{{ s.id }}" style="display:inline;"><button type="submit" class="btn btn-danger" style="font-size:11px;padding:4px 10px;">Remove</button></form>
                            </div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                <div class="section">
                    <div class="section-header"><h2>Custom Keywords</h2><span class="badge">{{ keywords | length }}</span></div>
                    <div class="section-body">
                        <form method="POST" action="/settings/add-keyword" class="inline-form">
                            <input type="text" name="keyword" placeholder="losing hope, itchy scalp" required>
                            <select name="tier"><option value="3">Tier 3</option><option value="2" selected>Tier 2</option><option value="1">Tier 1</option></select>
                            <button type="submit" class="btn btn-primary">Add</button>
                        </form>
                        {% for kw in keywords %}
                        <div class="item-row">
                            <div><span style="color:#fff;">{{ kw.keyword }}</span><span class="tier-badge tier-{{ kw.tier }}">{{ 'Desperation' if kw.tier == 3 else 'Frustration' if kw.tier == 2 else 'Concern' }}</span></div>
                            <div class="item-actions"><form method="POST" action="/settings/remove-keyword/{{ kw.id }}" style="display:inline;"><button type="submit" class="btn btn-danger" style="font-size:11px;padding:4px 10px;">Remove</button></form></div>
                        </div>
                        {% endfor %}
                        <div style="margin-top:16px;padding-top:16px;border-top:1px solid #2a2a2a;">
                            <p style="color:#555;font-size:11px;margin-bottom:8px;">BUILT-IN SIGNALS:</p>
                            <div style="display:flex;flex-wrap:wrap;gap:4px;">{% for sig, weight in builtin_signals.items() %}<span class="signal-tag">{{ sig }} <span style="color:#555;">({{ weight }})</span></span>{% endfor %}</div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="section" style="margin-top:0;">
                <div class="section-header"><h2>API Status</h2></div>
                <div class="section-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
                    <div><span style="font-size:12px;color:#888;">Anthropic</span><br><span style="font-size:12px;color:{{ '#4ade80' if env.ANTHROPIC_API_KEY else '#ef4444' }};">{{ 'Connected' if env.ANTHROPIC_API_KEY else 'Missing' }}</span></div>
                    <div><span style="font-size:12px;color:#888;">Reddit</span><br><span style="font-size:12px;color:#4ade80;">Public JSON (no key)</span></div>
                    <div><span style="font-size:12px;color:#888;">Product</span><br><span style="font-size:12px;color:{{ '#4ade80' if env.PRODUCT_NAME else '#f59e0b' }};">{{ env.PRODUCT_NAME or 'Not set' }}</span></div>
                </div>
            </div>
        {% endif %}
        </div>
        </div>
    </div>

    <!-- LIVE SIDEBAR -->
    <div class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <h3>Live Activity</h3>
            <div class="sidebar-status">
                <div class="status-dot idle" id="statusDot"></div>
                <span class="status-label" id="statusLabel">Idle</span>
            </div>
        </div>
        <div class="sidebar-feed" id="feed">
            <div class="feed-empty" id="feedEmpty">No activity yet. Run the pipeline to see live updates.</div>
        </div>
        <div class="sidebar-actions">
            <button class="btn btn-pipeline" id="btnPipeline" onclick="runPipeline('full')">Run Full Pipeline</button>
            <button class="btn btn-muted" style="width:100%;text-align:center;" onclick="runPipeline('scan')">Scan Only</button>
        </div>
    </div>
</div>

<script>
// SSE connection for live updates
const feed = document.getElementById('feed');
const feedEmpty = document.getElementById('feedEmpty');
const statusDot = document.getElementById('statusDot');
const statusLabel = document.getElementById('statusLabel');
const btnPipeline = document.getElementById('btnPipeline');

const icons = {
    scan: '&#x1F50D;',
    pain: '&#x1F525;',
    qualify: '&#x1F9E0;',
    lead: '&#x2705;',
    draft: '&#x270D;&#xFE0F;',
    error: '&#x274C;',
    done: '&#x1F389;',
    info: '&#x2139;&#xFE0F;'
};

function addFeedItem(entry) {
    if (feedEmpty) feedEmpty.style.display = 'none';
    const div = document.createElement('div');
    div.className = 'feed-item type-' + entry.type;
    let html = '<div class="feed-time">' + entry.time + '</div>';
    html += '<div class="feed-msg"><span class="feed-icon">' + (icons[entry.type] || '') + '</span>' + entry.msg + '</div>';
    if (entry.data && entry.data.detail) {
        html += '<div class="feed-detail">' + entry.data.detail + '</div>';
    }
    div.innerHTML = html;
    feed.insertBefore(div, feed.firstChild);
    // Keep max 50 items
    while (feed.children.length > 51) feed.removeChild(feed.lastChild);
}

function setRunning(running) {
    statusDot.className = 'status-dot ' + (running ? 'running' : 'idle');
    statusLabel.textContent = running ? 'Running...' : 'Idle';
    btnPipeline.disabled = running;
    btnPipeline.textContent = running ? 'Pipeline Running...' : 'Run Full Pipeline';
}

// Connect SSE
const evtSource = new EventSource('/stream');
evtSource.onmessage = function(e) {
    const entry = JSON.parse(e.data);
    addFeedItem(entry);
    if (entry.type === 'done' || entry.type === 'error') {
        setRunning(false);
        // Refresh stats after pipeline completes
        setTimeout(() => location.reload(), 2000);
    }
    if (entry.type === 'scan' && entry.msg.includes('Starting')) {
        setRunning(true);
    }
};

// Load existing log
fetch('/api/activity').then(r => r.json()).then(items => {
    items.forEach(addFeedItem);
    // Check if pipeline is running
    fetch('/api/pipeline-status').then(r => r.json()).then(s => setRunning(s.running));
});

function runPipeline(mode) {
    setRunning(true);
    fetch('/run-pipeline', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})
    });
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    stats = store.stats()
    recent_pp = store.get_unqualified_pain_points(min_score=0, limit=10)
    subreddits = store.get_subreddits()
    return render_template_string(TEMPLATE, page="dashboard", stats=stats,
                                  recent_pp=recent_pp, subreddits=subreddits, flash=_get_flash())

@app.route("/pain-points")
def pain_points():
    return render_template_string(TEMPLATE, page="pain_points",
                                  items=store.get_unqualified_pain_points(min_score=0, limit=200), flash=_get_flash())

@app.route("/leads")
def leads():
    return render_template_string(TEMPLATE, page="leads",
                                  items=store.get_undrafted_leads(min_score=0, limit=200), flash=_get_flash())

@app.route("/outbox")
def outbox():
    return render_template_string(TEMPLATE, page="outbox",
                                  items=store.get_unsent_outreach(limit=200), flash=_get_flash())

@app.route("/settings")
def settings():
    from agents.scanner import PAIN_SIGNALS
    env = {"ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""), "PRODUCT_NAME": os.getenv("PRODUCT_NAME", "")}
    return render_template_string(TEMPLATE, page="settings", env=env,
                                  subreddits=store.get_subreddits(), keywords=store.get_custom_keywords(),
                                  builtin_signals=PAIN_SIGNALS, flash=_get_flash())


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------
@app.route("/stream")
def stream():
    def event_stream():
        q = queue.Queue(maxsize=100)
        sse_clients.append(q)
        try:
            while True:
                try:
                    entry = q.get(timeout=30)
                    yield f"data: {json.dumps(entry)}\n\n"
                except queue.Empty:
                    yield f": keepalive\n\n"
        except GeneratorExit:
            if q in sse_clients:
                sse_clients.remove(q)

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/activity")
def api_activity():
    return jsonify(list(reversed(activity_log[-30:])))


@app.route("/api/pipeline-status")
def api_pipeline_status():
    return jsonify({"running": pipeline_running})


# ---------------------------------------------------------------------------
# Run Pipeline (with live events)
# ---------------------------------------------------------------------------
@app.route("/run-pipeline", methods=["POST"])
def run_pipeline_route():
    global pipeline_running
    if pipeline_running:
        return jsonify({"error": "Pipeline already running"}), 409

    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "full")

    def _bg_pipeline():
        global pipeline_running
        pipeline_running = True
        try:
            from agents.scanner import scan_multi, reload_signals
            from agents.qualifier import qualify_leads
            from agents.writer import draft_messages

            reload_signals()
            subreddits = store.get_subreddits(enabled_only=True)
            if not subreddits:
                emit("error", "No subreddits configured")
                return

            # --- SCAN ---
            emit("scan", f"Starting pipeline ({mode} mode)")
            all_pain_points = []
            for sub in subreddits:
                emit("scan", f"Scanning r/{sub['name']}...")
                try:
                    results = scan_multi(sub["name"], post_limit=15, min_score=2)
                    run_id = store.start_run(sub["name"])
                    new_ids = store.save_pain_points(results, run_id)
                    store.finish_run(run_id, {"posts_scanned": 45, "pain_points_found": len(results)}, "completed")
                    all_pain_points.extend(results)
                    emit("pain", f"Found {len(results)} pain points in r/{sub['name']}",
                         {"detail": f"{len(new_ids)} new, {len(results)-len(new_ids)} already seen"})
                except Exception as e:
                    emit("error", f"Scan failed for r/{sub['name']}: {str(e)[:80]}")

            if not all_pain_points:
                emit("done", "Scan complete. No pain points found.")
                return

            # Show top finds
            top3 = sorted(all_pain_points, key=lambda x: x["score"], reverse=True)[:3]
            for pp in top3:
                sigs = ", ".join(pp["matched_signals"][:3])
                emit("pain", f"u/{pp['author']} (score: {pp['score']})",
                     {"detail": f"Signals: {sigs}"})

            if mode == "scan":
                emit("done", f"Scan complete! {len(all_pain_points)} pain points found.")
                return

            # --- QUALIFY ---
            if not ANTHROPIC_API_KEY:
                emit("info", "Skipping qualification (no Anthropic key)")
                emit("done", f"Scan complete! {len(all_pain_points)} pain points. Add ANTHROPIC_API_KEY for full pipeline.")
                return

            emit("qualify", "Qualifying top pain points with Claude...")
            candidates = [p for p in all_pain_points if p["score"] >= 4][:10]
            emit("qualify", f"Sending {len(candidates)} candidates to Claude API...")

            try:
                qualified = qualify_leads(candidates, min_pain_score=0, min_lead_score=4, batch_size=10)
                emit("qualify", f"Claude returned {len(qualified)} qualified leads")

                # Save leads
                for q in qualified:
                    # Find pain point ID
                    stored = store.get_unqualified_pain_points(min_score=0, limit=500)
                    pp_id = None
                    for s in stored:
                        if s.get("source_url") == q.get("source_url"):
                            pp_id = s["id"]
                            break
                    if pp_id:
                        store.save_lead(pp_id, q["lead_score"], q["buy_intent"],
                                        q["urgency"], q["solvability"], q["reasoning"], run_id)

                for q in qualified[:3]:
                    emit("lead", f"u/{q['author']} qualified (score: {q['lead_score']})",
                         {"detail": f"Buy: {q['buy_intent']}/10 | Urg: {q['urgency']}/10 | Sol: {q['solvability']}/10"})

            except Exception as e:
                emit("error", f"Qualification failed: {str(e)[:100]}")
                emit("done", f"Partial pipeline: {len(all_pain_points)} pain points scanned.")
                return

            if not qualified:
                emit("done", f"Pipeline complete. {len(all_pain_points)} pain points, 0 qualified leads.")
                return

            # --- DRAFT ---
            emit("draft", f"Drafting outreach for {min(len(qualified), 3)} top leads...")
            try:
                top_leads = qualified[:3]
                drafts = draft_messages(top_leads, tone="empathetic", max_length=200, batch_size=3)

                # Save drafts
                undrafted = store.get_undrafted_leads(min_score=0, limit=500)
                for d in drafts:
                    for ul in undrafted:
                        if ul.get("pp_author") == d.get("author") or ul.get("pp_url") == d.get("source_url"):
                            store.save_outreach(ul["id"], d["draft_message"], "empathetic",
                                                d.get("word_count", 0), run_id)
                            break

                for d in drafts:
                    hook = d.get("hook", "personalized message")
                    emit("draft", f"Drafted message for u/{d.get('author', '?')}",
                         {"detail": f"Hook: {hook[:60]}... ({d.get('word_count', 0)} words)"})

            except Exception as e:
                emit("error", f"Drafting failed: {str(e)[:100]}")

            emit("done", f"Pipeline complete! {len(all_pain_points)} scanned, {len(qualified)} qualified, {len(drafts)} drafted")

        except Exception as e:
            emit("error", f"Pipeline error: {str(e)[:100]}")
        finally:
            pipeline_running = False

    thread = threading.Thread(target=_bg_pipeline, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


# ---------------------------------------------------------------------------
# Settings routes (same as before)
# ---------------------------------------------------------------------------
@app.route("/settings/add-subreddit", methods=["POST"])
def add_subreddit():
    names = [n.strip().lower().replace("r/", "") for n in request.form.get("name", "").split(",") if n.strip()]
    added = sum(1 for n in names if store.add_subreddit(n))
    _set_flash("success" if added else "error", f"Added {added} subreddit(s)" if added else "Already exists")
    return redirect(url_for("settings"))

@app.route("/settings/remove-subreddit/<int:sub_id>", methods=["POST"])
def remove_subreddit(sub_id):
    store.remove_subreddit(sub_id)
    return redirect(url_for("settings"))

@app.route("/settings/toggle-subreddit/<int:sub_id>", methods=["POST"])
def toggle_subreddit(sub_id):
    store.toggle_subreddit(sub_id)
    return redirect(url_for("settings"))

@app.route("/settings/add-keyword", methods=["POST"])
def add_keyword():
    keywords = [k.strip().lower() for k in request.form.get("keyword", "").split(",") if k.strip()]
    tier = int(request.form.get("tier", 2))
    added = sum(1 for k in keywords if store.add_keyword(k, tier))
    if added:
        from agents.scanner import reload_signals
        reload_signals()
    _set_flash("success" if added else "error", f"Added {added} keyword(s)" if added else "Already exists")
    return redirect(url_for("settings"))

@app.route("/settings/remove-keyword/<int:kw_id>", methods=["POST"])
def remove_keyword(kw_id):
    store.remove_keyword(kw_id)
    from agents.scanner import reload_signals
    reload_signals()
    return redirect(url_for("settings"))

# JSON API
@app.route("/api/stats")
def api_stats(): return jsonify(store.stats())
@app.route("/api/pain-points")
def api_pain_points(): return jsonify(store.get_unqualified_pain_points(min_score=0, limit=200))
@app.route("/api/leads")
def api_leads(): return jsonify(store.get_undrafted_leads(min_score=0, limit=200))
@app.route("/api/outbox")
def api_outbox(): return jsonify(store.get_unsent_outreach(limit=200))

# Flash
_flash_msg = None
def _set_flash(t, m):
    global _flash_msg
    _flash_msg = {"type": t, "msg": m}
def _get_flash():
    global _flash_msg
    m = _flash_msg
    _flash_msg = None
    return m

if __name__ == "__main__":
    print("\n  Pain Point Machine Dashboard")
    print("  http://localhost:5000\n")
    app.run(debug=False, port=5000, threaded=True)
