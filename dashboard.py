#!/usr/bin/env python3
"""
Pain Point Machine — Web Dashboard

Run: python dashboard.py
Open: http://localhost:5000
"""

import json
import os
import threading
from datetime import datetime, timezone

from flask import Flask, render_template_string, jsonify, request, redirect, url_for
from agents.store import Store
from agents.config import DEFAULT_SUBREDDIT

app = Flask(__name__)
store = Store()

# Seed default subreddit if table is empty
if not store.get_subreddits():
    store.add_subreddit(DEFAULT_SUBREDDIT)

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

        .nav { background: #1a1a1a; border-bottom: 1px solid #2a2a2a; padding: 16px 32px; display: flex; align-items: center; justify-content: space-between; }
        .nav h1 { font-size: 20px; color: #ff6b35; }
        .nav h1 span { color: #888; font-weight: 400; font-size: 14px; margin-left: 8px; }
        .nav-links { display: flex; gap: 8px; }
        .nav-links a { color: #888; text-decoration: none; padding: 8px 16px; border-radius: 8px; font-size: 14px; transition: all 0.2s; }
        .nav-links a:hover, .nav-links a.active { background: #2a2a2a; color: #fff; }

        .container { max-width: 1200px; margin: 0 auto; padding: 24px; }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }
        .stat-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 20px; }
        .stat-card .label { font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
        .stat-card .value { font-size: 32px; font-weight: 700; color: #ff6b35; }
        .stat-card .value.green { color: #4ade80; }
        .stat-card .value.blue { color: #60a5fa; }
        .stat-card .value.purple { color: #a78bfa; }

        .section { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; margin-bottom: 24px; overflow: hidden; }
        .section-header { padding: 16px 20px; border-bottom: 1px solid #2a2a2a; display: flex; justify-content: space-between; align-items: center; }
        .section-header h2 { font-size: 16px; color: #fff; }
        .section-header .badge { background: #ff6b35; color: #000; font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 99px; }
        .section-body { padding: 20px; }

        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; padding: 12px 16px; font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid #2a2a2a; }
        td { padding: 12px 16px; font-size: 14px; border-bottom: 1px solid #1f1f1f; vertical-align: top; }
        tr:hover { background: #222; }

        .score-badge { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 12px; font-weight: 600; }
        .score-high { background: #ff6b3520; color: #ff6b35; }
        .score-med { background: #f59e0b20; color: #f59e0b; }
        .score-low { background: #6b728020; color: #9ca3af; }

        .signal-tag { display: inline-block; background: #2a2a2a; color: #aaa; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 1px 2px; }
        .text-preview { color: #888; font-size: 13px; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .author { color: #60a5fa; font-size: 13px; }
        .link { color: #666; font-size: 12px; text-decoration: none; }
        .link:hover { color: #ff6b35; }

        .msg-card { background: #111; border: 1px solid #2a2a2a; border-radius: 8px; padding: 16px; margin: 8px 16px 16px; }
        .msg-card .msg-meta { font-size: 12px; color: #666; margin-bottom: 8px; }
        .msg-card .msg-body { font-size: 14px; color: #ccc; line-height: 1.6; white-space: pre-wrap; }

        .status { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 11px; font-weight: 600; }
        .status-new { background: #3b82f620; color: #60a5fa; }
        .status-contacted { background: #4ade8020; color: #4ade80; }
        .status-converted { background: #a78bfa20; color: #a78bfa; }

        .empty { text-align: center; padding: 60px 20px; color: #555; }
        .empty h3 { font-size: 18px; margin-bottom: 8px; color: #666; }
        .empty p { font-size: 14px; }
        .empty code { background: #2a2a2a; padding: 4px 8px; border-radius: 4px; color: #ff6b35; }

        .setup-banner { background: #1a1a00; border: 1px solid #433d00; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
        .setup-banner h3 { color: #f59e0b; margin-bottom: 8px; }
        .setup-banner p { color: #aaa; font-size: 14px; line-height: 1.6; }
        .setup-banner code { background: #2a2a2a; padding: 2px 6px; border-radius: 4px; color: #ff6b35; font-size: 13px; }

        /* Forms */
        .inline-form { display: flex; gap: 8px; align-items: center; margin-bottom: 16px; }
        .inline-form input, .inline-form select { padding: 8px 12px; background: #111; border: 1px solid #333; border-radius: 8px; color: #fff; font-size: 14px; }
        .inline-form input:focus, .inline-form select:focus { border-color: #ff6b35; outline: none; }
        .inline-form input[type="text"] { flex: 1; min-width: 200px; }

        .btn { padding: 8px 16px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.2s; text-decoration: none; display: inline-block; }
        .btn-primary { background: #ff6b35; color: #000; }
        .btn-primary:hover { background: #ff8c5a; }
        .btn-danger { background: #dc262620; color: #ef4444; border: 1px solid #dc262640; }
        .btn-danger:hover { background: #dc262640; }
        .btn-success { background: #16a34a20; color: #4ade80; border: 1px solid #16a34a40; }
        .btn-success:hover { background: #16a34a40; }
        .btn-muted { background: #2a2a2a; color: #888; }
        .btn-muted:hover { background: #333; color: #fff; }
        .btn-scan { background: #3b82f6; color: #fff; padding: 10px 20px; font-size: 14px; }
        .btn-scan:hover { background: #2563eb; }

        .item-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid #1f1f1f; }
        .item-row:last-child { border-bottom: none; }
        .item-row .item-name { font-size: 14px; }
        .item-row .item-meta { font-size: 12px; color: #666; margin-left: 8px; }
        .item-row .item-actions { display: flex; gap: 6px; }

        .tier-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 8px; }
        .tier-3 { background: #dc262620; color: #ef4444; }
        .tier-2 { background: #f59e0b20; color: #f59e0b; }
        .tier-1 { background: #6b728020; color: #9ca3af; }

        .sub-badge { display: inline-block; background: #ff6b3515; color: #ff6b35; padding: 4px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; }
        .sub-disabled { opacity: 0.4; }

        .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }

        .flash { padding: 12px 20px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
        .flash-success { background: #16a34a20; color: #4ade80; border: 1px solid #16a34a40; }
        .flash-error { background: #dc262620; color: #ef4444; border: 1px solid #dc262640; }
        .flash-info { background: #3b82f620; color: #60a5fa; border: 1px solid #3b82f640; }
    </style>
</head>
<body>
    <div class="nav">
        <h1>Pain Point Machine <span>v1.1</span></h1>
        <div class="nav-links">
            <a href="/" class="{{ 'active' if page == 'dashboard' else '' }}">Dashboard</a>
            <a href="/pain-points" class="{{ 'active' if page == 'pain_points' else '' }}">Pain Points</a>
            <a href="/leads" class="{{ 'active' if page == 'leads' else '' }}">Leads</a>
            <a href="/outbox" class="{{ 'active' if page == 'outbox' else '' }}">Outbox</a>
            <a href="/settings" class="{{ 'active' if page == 'settings' else '' }}">Settings</a>
        </div>
    </div>

    <div class="container">
    {% if flash %}
        <div class="flash flash-{{ flash.type }}">{{ flash.msg }}</div>
    {% endif %}

    {% if page == 'dashboard' %}
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Pain Points</div>
                <div class="value">{{ stats.total_pain_points }}</div>
            </div>
            <div class="stat-card">
                <div class="label">Qualified Leads</div>
                <div class="value green">{{ stats.total_leads }}</div>
            </div>
            <div class="stat-card">
                <div class="label">Drafts Ready</div>
                <div class="value blue">{{ stats.total_drafts }}</div>
            </div>
            <div class="stat-card">
                <div class="label">Messages Sent</div>
                <div class="value purple">{{ stats.total_sent }}</div>
            </div>
            <div class="stat-card">
                <div class="label">Subreddits</div>
                <div class="value">{{ subreddits | length }}</div>
            </div>
        </div>

        <!-- Active subreddits -->
        <div style="margin-bottom: 24px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
            <span style="color: #666; font-size: 13px; margin-right: 4px;">Scanning:</span>
            {% for s in subreddits %}
                <span class="sub-badge {{ 'sub-disabled' if not s.enabled else '' }}">r/{{ s.name }}</span>
            {% endfor %}
            <a href="/settings" class="btn btn-muted" style="font-size: 12px; padding: 4px 12px;">+ Add</a>
        </div>

        {% if stats.total_pain_points == 0 %}
        <div class="setup-banner">
            <h3>Get Started</h3>
            <p>
                1. Add subreddits and keywords in <a href="/settings" style="color: #ff6b35;">Settings</a><br>
                2. Hit "Scan Now" or run <code>python main.py scan</code><br>
                3. Add your Anthropic key in <code>.env</code> to unlock qualify + draft
            </p>
        </div>
        {% endif %}

        <!-- Scan button -->
        <div style="margin-bottom: 24px;">
            <form method="POST" action="/scan-now" style="display: inline;">
                <button type="submit" class="btn btn-scan">Scan Now</button>
            </form>
            <span style="color: #555; font-size: 13px; margin-left: 12px;">Scans all enabled subreddits (takes ~1 min)</span>
        </div>

        <div class="section">
            <div class="section-header">
                <h2>Recent Pain Points</h2>
                <span class="badge">{{ recent_pp | length }}</span>
            </div>
            {% if recent_pp %}
            <table>
                <tr><th>Score</th><th>Author</th><th>Text</th><th>Signals</th><th>Age</th></tr>
                {% for pp in recent_pp[:10] %}
                <tr>
                    <td><span class="score-badge {{ 'score-high' if pp.score >= 8 else 'score-med' if pp.score >= 4 else 'score-low' }}">{{ pp.score }}</span></td>
                    <td><span class="author">u/{{ pp.author }}</span></td>
                    <td><div class="text-preview">{{ pp.text[:120] }}</div></td>
                    <td>{% for s in (pp.matched_signals or [])[:3] %}<span class="signal-tag">{{ s }}</span>{% endfor %}</td>
                    <td style="color: #666; font-size: 13px;">{{ pp.age_days }}d</td>
                </tr>
                {% endfor %}
            </table>
            {% else %}
            <div class="empty"><h3>No pain points yet</h3><p>Click "Scan Now" above</p></div>
            {% endif %}
        </div>

    {% elif page == 'pain_points' %}
        <div class="section">
            <div class="section-header">
                <h2>All Pain Points</h2>
                <span class="badge">{{ items | length }}</span>
            </div>
            {% if items %}
            <table>
                <tr><th>Score</th><th>Type</th><th>Author</th><th>Text</th><th>Signals</th><th>Upvotes</th><th>Link</th></tr>
                {% for pp in items %}
                <tr>
                    <td><span class="score-badge {{ 'score-high' if pp.score >= 8 else 'score-med' if pp.score >= 4 else 'score-low' }}">{{ pp.score }}</span></td>
                    <td style="color: #666; font-size: 12px;">{{ 'comment' if pp.is_comment else 'post' }}</td>
                    <td><span class="author">u/{{ pp.author }}</span></td>
                    <td><div class="text-preview">{{ pp.text[:150] }}</div></td>
                    <td>{% for s in (pp.matched_signals or [])[:4] %}<span class="signal-tag">{{ s }}</span>{% endfor %}</td>
                    <td style="color: #666;">{{ pp.upvotes }}</td>
                    <td><a class="link" href="{{ pp.source_url }}" target="_blank">open</a></td>
                </tr>
                {% endfor %}
            </table>
            {% else %}
            <div class="empty"><h3>No pain points yet</h3><p>Run a scan first</p></div>
            {% endif %}
        </div>

    {% elif page == 'leads' %}
        <div class="section">
            <div class="section-header">
                <h2>Qualified Leads</h2>
                <span class="badge">{{ items | length }}</span>
            </div>
            {% if items %}
            <table>
                <tr><th>Lead Score</th><th>Author</th><th>Buy</th><th>Urgency</th><th>Solvability</th><th>Reasoning</th><th>Status</th></tr>
                {% for l in items %}
                <tr>
                    <td><span class="score-badge {{ 'score-high' if l.lead_score >= 7 else 'score-med' if l.lead_score >= 5 else 'score-low' }}">{{ l.lead_score }}</span></td>
                    <td><span class="author">u/{{ l.pp_author or '?' }}</span></td>
                    <td style="color: #4ade80;">{{ l.buy_intent }}/10</td>
                    <td style="color: #f59e0b;">{{ l.urgency }}/10</td>
                    <td style="color: #60a5fa;">{{ l.solvability }}/10</td>
                    <td><div class="text-preview">{{ l.reasoning[:120] if l.reasoning else '' }}</div></td>
                    <td><span class="status status-{{ l.status or 'new' }}">{{ l.status or 'new' }}</span></td>
                </tr>
                {% endfor %}
            </table>
            {% else %}
            <div class="empty"><h3>No qualified leads yet</h3><p>Run <code>python main.py qualify</code></p></div>
            {% endif %}
        </div>

    {% elif page == 'outbox' %}
        <div class="section">
            <div class="section-header">
                <h2>Outreach Drafts</h2>
                <span class="badge">{{ items | length }}</span>
            </div>
            {% if items %}
                {% for o in items %}
                <div class="msg-card">
                    <div class="msg-meta">
                        To: <span class="author">u/{{ o.pp_author or '?' }}</span>
                        &middot; Lead score: {{ o.lead_score or '?' }}
                        &middot; {{ o.word_count or '?' }} words
                        &middot; <a class="link" href="{{ o.pp_url or '#' }}" target="_blank">source</a>
                    </div>
                    <div class="msg-body">{{ o.message }}</div>
                </div>
                {% endfor %}
            {% else %}
            <div class="empty"><h3>No drafts yet</h3><p>Run <code>python main.py draft</code></p></div>
            {% endif %}
        </div>

    {% elif page == 'settings' %}
        <div class="two-col">
            <!-- SUBREDDITS -->
            <div class="section">
                <div class="section-header">
                    <h2>Subreddits</h2>
                    <span class="badge">{{ subreddits | length }}</span>
                </div>
                <div class="section-body">
                    <form method="POST" action="/settings/add-subreddit" class="inline-form">
                        <input type="text" name="name" placeholder="e.g. tressless, alopecia, haircare" required>
                        <button type="submit" class="btn btn-primary">Add</button>
                    </form>
                    {% for s in subreddits %}
                    <div class="item-row">
                        <div>
                            <span class="sub-badge {{ 'sub-disabled' if not s.enabled else '' }}">r/{{ s.name }}</span>
                            {% if not s.enabled %}<span class="item-meta">(paused)</span>{% endif %}
                        </div>
                        <div class="item-actions">
                            <form method="POST" action="/settings/toggle-subreddit/{{ s.id }}" style="display:inline;">
                                <button type="submit" class="btn {{ 'btn-muted' if s.enabled else 'btn-success' }}" style="font-size: 11px; padding: 4px 10px;">
                                    {{ 'Pause' if s.enabled else 'Enable' }}
                                </button>
                            </form>
                            <form method="POST" action="/settings/remove-subreddit/{{ s.id }}" style="display:inline;">
                                <button type="submit" class="btn btn-danger" style="font-size: 11px; padding: 4px 10px;">Remove</button>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                    {% if not subreddits %}
                    <p style="color: #555; font-size: 13px; padding: 12px 0;">No subreddits added yet. Add one above.</p>
                    {% endif %}
                </div>
            </div>

            <!-- KEYWORDS -->
            <div class="section">
                <div class="section-header">
                    <h2>Custom Keywords</h2>
                    <span class="badge">{{ keywords | length }}</span>
                </div>
                <div class="section-body">
                    <form method="POST" action="/settings/add-keyword" class="inline-form">
                        <input type="text" name="keyword" placeholder="e.g. losing hope, broke out, itchy scalp" required>
                        <select name="tier">
                            <option value="3">Tier 3 (desperation)</option>
                            <option value="2" selected>Tier 2 (frustration)</option>
                            <option value="1">Tier 1 (concern)</option>
                        </select>
                        <button type="submit" class="btn btn-primary">Add</button>
                    </form>
                    {% for kw in keywords %}
                    <div class="item-row">
                        <div>
                            <span style="color: #fff;">{{ kw.keyword }}</span>
                            <span class="tier-badge tier-{{ kw.tier }}">
                                {{ 'Desperation' if kw.tier == 3 else 'Frustration' if kw.tier == 2 else 'Concern' }}
                            </span>
                        </div>
                        <div class="item-actions">
                            <form method="POST" action="/settings/remove-keyword/{{ kw.id }}" style="display:inline;">
                                <button type="submit" class="btn btn-danger" style="font-size: 11px; padding: 4px 10px;">Remove</button>
                            </form>
                        </div>
                    </div>
                    {% endfor %}
                    {% if not keywords %}
                    <p style="color: #555; font-size: 13px; padding: 12px 0;">No custom keywords. The scanner uses 40+ built-in signals by default. Add extras here.</p>
                    {% endif %}

                    <div style="margin-top: 16px; padding-top: 16px; border-top: 1px solid #2a2a2a;">
                        <p style="color: #555; font-size: 12px; margin-bottom: 8px;">BUILT-IN SIGNALS (always active):</p>
                        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
                            {% for sig, weight in builtin_signals.items() %}
                            <span class="signal-tag">{{ sig }} <span style="color: #555;">({{ weight }})</span></span>
                            {% endfor %}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- API Status -->
        <div class="section" style="margin-top: 0;">
            <div class="section-header"><h2>API Status</h2></div>
            <div class="section-body" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px;">
                <div>
                    <span style="font-size: 13px; color: #888;">Anthropic API</span><br>
                    <span style="font-size: 12px; color: {{ '#4ade80' if env.ANTHROPIC_API_KEY else '#ef4444' }};">
                        {{ 'Connected' if env.ANTHROPIC_API_KEY else 'Not configured — add ANTHROPIC_API_KEY to .env' }}
                    </span>
                </div>
                <div>
                    <span style="font-size: 13px; color: #888;">Reddit Scanner</span><br>
                    <span style="font-size: 12px; color: #4ade80;">Using public JSON feed (no key needed)</span>
                </div>
                <div>
                    <span style="font-size: 13px; color: #888;">Product Info</span><br>
                    <span style="font-size: 12px; color: {{ '#4ade80' if env.PRODUCT_NAME else '#f59e0b' }};">
                        {{ env.PRODUCT_NAME if env.PRODUCT_NAME else 'Not set — add PRODUCT_NAME to .env for outreach drafts' }}
                    </span>
                </div>
            </div>
        </div>
    {% endif %}
    </div>
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
    flash = _get_flash()
    return render_template_string(TEMPLATE, page="dashboard", stats=stats,
                                  recent_pp=recent_pp, subreddits=subreddits, flash=flash)


@app.route("/pain-points")
def pain_points():
    items = store.get_unqualified_pain_points(min_score=0, limit=200)
    return render_template_string(TEMPLATE, page="pain_points", items=items, flash=_get_flash())


@app.route("/leads")
def leads():
    items = store.get_undrafted_leads(min_score=0, limit=200)
    return render_template_string(TEMPLATE, page="leads", items=items, flash=_get_flash())


@app.route("/outbox")
def outbox():
    items = store.get_unsent_outreach(limit=200)
    return render_template_string(TEMPLATE, page="outbox", items=items, flash=_get_flash())


@app.route("/settings")
def settings():
    from agents.scanner import PAIN_SIGNALS
    env = {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "PRODUCT_NAME": os.getenv("PRODUCT_NAME", ""),
    }
    subreddits = store.get_subreddits()
    keywords = store.get_custom_keywords()
    return render_template_string(TEMPLATE, page="settings", env=env,
                                  subreddits=subreddits, keywords=keywords,
                                  builtin_signals=PAIN_SIGNALS, flash=_get_flash())


# ---------------------------------------------------------------------------
# Subreddit management
# ---------------------------------------------------------------------------
@app.route("/settings/add-subreddit", methods=["POST"])
def add_subreddit():
    name = request.form.get("name", "").strip()
    # Support comma-separated: "tressless, alopecia, haircare"
    names = [n.strip().lower().replace("r/", "") for n in name.split(",") if n.strip()]
    added = 0
    for n in names:
        if store.add_subreddit(n):
            added += 1
    if added:
        _set_flash("success", f"Added {added} subreddit(s)")
    else:
        _set_flash("error", "Already exists or invalid name")
    return redirect(url_for("settings"))


@app.route("/settings/remove-subreddit/<int:sub_id>", methods=["POST"])
def remove_subreddit(sub_id):
    store.remove_subreddit(sub_id)
    _set_flash("success", "Subreddit removed")
    return redirect(url_for("settings"))


@app.route("/settings/toggle-subreddit/<int:sub_id>", methods=["POST"])
def toggle_subreddit(sub_id):
    store.toggle_subreddit(sub_id)
    _set_flash("success", "Subreddit toggled")
    return redirect(url_for("settings"))


# ---------------------------------------------------------------------------
# Keyword management
# ---------------------------------------------------------------------------
@app.route("/settings/add-keyword", methods=["POST"])
def add_keyword():
    keyword = request.form.get("keyword", "").strip()
    tier = int(request.form.get("tier", 2))
    # Support comma-separated: "itchy scalp, broke out, hair falling out"
    keywords = [k.strip().lower() for k in keyword.split(",") if k.strip()]
    added = 0
    for k in keywords:
        if store.add_keyword(k, tier):
            added += 1
    if added:
        # Invalidate scanner cache so new keywords take effect
        from agents.scanner import reload_signals
        reload_signals()
        _set_flash("success", f"Added {added} keyword(s)")
    else:
        _set_flash("error", "Already exists or invalid keyword")
    return redirect(url_for("settings"))


@app.route("/settings/remove-keyword/<int:kw_id>", methods=["POST"])
def remove_keyword(kw_id):
    store.remove_keyword(kw_id)
    from agents.scanner import reload_signals
    reload_signals()
    _set_flash("success", "Keyword removed")
    return redirect(url_for("settings"))


# ---------------------------------------------------------------------------
# Scan Now (runs in background thread)
# ---------------------------------------------------------------------------
@app.route("/scan-now", methods=["POST"])
def scan_now():
    subreddits = store.get_subreddits(enabled_only=True)
    if not subreddits:
        _set_flash("error", "No subreddits configured. Add some in Settings.")
        return redirect(url_for("dashboard"))

    def _bg_scan():
        from agents.scanner import scan_multi, reload_signals
        reload_signals()
        for sub in subreddits:
            try:
                results = scan_multi(sub["name"], post_limit=20, min_score=2)
                run_id = store.start_run(sub["name"])
                store.save_pain_points(results, run_id)
                store.finish_run(run_id, {
                    "posts_scanned": 60,
                    "pain_points_found": len(results),
                }, "completed")
            except Exception as e:
                print(f"Scan error for r/{sub['name']}: {e}")

    thread = threading.Thread(target=_bg_scan, daemon=True)
    thread.start()
    _set_flash("info", f"Scanning {len(subreddits)} subreddit(s) in background. Refresh in ~1 min.")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------
@app.route("/api/stats")
def api_stats():
    return jsonify(store.stats())

@app.route("/api/pain-points")
def api_pain_points():
    return jsonify(store.get_unqualified_pain_points(min_score=0, limit=200))

@app.route("/api/leads")
def api_leads():
    return jsonify(store.get_undrafted_leads(min_score=0, limit=200))

@app.route("/api/outbox")
def api_outbox():
    return jsonify(store.get_unsent_outreach(limit=200))

@app.route("/api/subreddits")
def api_subreddits():
    return jsonify(store.get_subreddits())

@app.route("/api/keywords")
def api_keywords():
    return jsonify(store.get_custom_keywords())


# ---------------------------------------------------------------------------
# Flash messages (simple, no session needed)
# ---------------------------------------------------------------------------
_flash_msg = None

def _set_flash(msg_type: str, msg: str):
    global _flash_msg
    _flash_msg = {"type": msg_type, "msg": msg}

def _get_flash():
    global _flash_msg
    msg = _flash_msg
    _flash_msg = None
    return msg


if __name__ == "__main__":
    print("\n  Pain Point Machine Dashboard")
    print("  http://localhost:5000\n")
    app.run(debug=False, port=5000)
