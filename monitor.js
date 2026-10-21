/* Harbourline MongoDB monitor.
   Frontend plugin: docked beside the bake-off page. No server.
   Query text is the Side B commands (bank adapter, freeze, change stream, audit).
   Regenerate from demo/scene_playback.py if those commands change. */
(function (global) {
  var CATALOG = /* QUERIES_START */
{
  "residency": {
    "title": "Where memory lives",
    "db": "harbourline",
    "queries": [
      {
        "db": "harbourline",
        "collection": "short_term",
        "operation": "insertOne",
        "source": "memory",
        "label": "Short-term memory: store the customer turn",
        "mongosh": "db.short_term.insertOne(\n{\n  \"user_id\": \"C-1001\",\n  \"role\": \"user\",\n  \"text\": \"I'm moving to Melbourne for work next month. I'll keep using this card there.\"\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "semantic",
        "operation": "updateOne",
        "source": "memory",
        "label": "save_semantic · relocation",
        "mongosh": "db.semantic.updateOne(\n{\n  \"user_id\": \"C-1001\",\n  \"label\": \"relocation\"\n},\n{\n  \"$set\": {\n    \"text\": \"Customer is relocating to Melbourne for work next month and will keep using this card there.\",\n    \"user_id\": \"C-1001\",\n    \"label\": \"relocation\",\n    \"metadata\": {\n      \"kind\": \"fact\",\n      \"customer_id\": \"C-1001\"\n    }\n  }\n},\n{\n  \"upsert\": true\n}\n)",
        "result_count": 1,
        "note": null
      }
    ]
  },
  "stale": {
    "title": "Fraud freeze",
    "db": "harbourline",
    "queries": [
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "updateOne",
        "source": "bank",
        "label": "System of record: fraud ops freezes the card",
        "mongosh": "db.accounts.updateOne(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"$set\": {\n    \"status\": \"frozen\",\n    \"hold_reason\": \"fraud review\"\n  }\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "watch",
        "source": "stream",
        "label": "Change stream: watch accounts for a status change",
        "mongosh": "db.accounts.watch(\n[\n  {\n    \"$match\": {\n      \"operationType\": {\n        \"$in\": [\n          \"update\",\n          \"replace\"\n        ]\n      }\n    }\n  },\n  {\n    \"$match\": {\n      \"$or\": [\n        {\n          \"updateDescription.updatedFields.status\": {\n            \"$exists\": true\n          }\n        },\n        {\n          \"operationType\": \"replace\"\n        }\n      ]\n    }\n  }\n],\n{\n  \"fullDocument\": \"updateLookup\"\n}\n)",
        "result_count": null,
        "note": "Listener registered. The freeze above is the event it is waiting for."
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "aggregate",
        "source": "audit",
        "label": "Audit: frozen customers whose memory still holds an offer",
        "mongosh": "db.accounts.aggregate(\n[\n  {\n    \"$match\": {\n      \"status\": {\n        \"$ne\": \"active\"\n      }\n    }\n  },\n  {\n    \"$lookup\": {\n      \"from\": \"semantic\",\n      \"localField\": \"customer_id\",\n      \"foreignField\": \"user_id\",\n      \"pipeline\": [\n        {\n          \"$match\": {\n            \"text\": {\n              \"$regex\": \"offer|pre-?qualified|limit increase\",\n              \"$options\": \"i\"\n            },\n            \"metadata.stale\": {\n              \"$ne\": true\n            }\n          }\n        }\n      ],\n      \"as\": \"mem\"\n    }\n  },\n  {\n    \"$unwind\": \"$mem\"\n  },\n  {\n    \"$project\": {\n      \"_id\": 0,\n      \"customer_id\": 1,\n      \"status\": 1,\n      \"memory\": \"$mem.text\"\n    }\n  }\n]\n)",
        "result_count": 1,
        "note": "Hit: Customer was pre-qualified on 2026-10-13 for a credit limit increase from SGD 18,000 to SGD 25,000. Customer said they would confirm later."
      },
      {
        "db": "harbourline",
        "collection": "semantic",
        "operation": "updateOne",
        "source": "memory",
        "label": "Watcher: withdraw the offer memory (upsert on the same label)",
        "mongosh": "db.semantic.updateOne(\n{\n  \"user_id\": \"C-1001\",\n  \"label\": \"credit-limit-offer\"\n},\n{\n  \"$set\": {\n    \"text\": \"WITHDRAWN on 2026-10-21: the earlier credit limit increase offer no longer applies. The account has a hold. Do not offer or discuss limit increases; a specialist will contact the customer.\",\n    \"metadata\": {\n      \"kind\": \"offer\",\n      \"customer_id\": \"C-1001\",\n      \"stale\": true,\n      \"stale_reason\": \"account hold\"\n    }\n  }\n},\n{\n  \"upsert\": true\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "aggregate",
        "source": "audit",
        "label": "Audit again, after the watcher withdraws the offer",
        "mongosh": "db.accounts.aggregate(\n[\n  {\n    \"$match\": {\n      \"status\": {\n        \"$ne\": \"active\"\n      }\n    }\n  },\n  {\n    \"$lookup\": {\n      \"from\": \"semantic\",\n      \"localField\": \"customer_id\",\n      \"foreignField\": \"user_id\",\n      \"pipeline\": [\n        {\n          \"$match\": {\n            \"text\": {\n              \"$regex\": \"offer|pre-?qualified|limit increase\",\n              \"$options\": \"i\"\n            },\n            \"metadata.stale\": {\n              \"$ne\": true\n            }\n          }\n        }\n      ],\n      \"as\": \"mem\"\n    }\n  },\n  {\n    \"$unwind\": \"$mem\"\n  },\n  {\n    \"$project\": {\n      \"_id\": 0,\n      \"customer_id\": 1,\n      \"status\": 1,\n      \"memory\": \"$mem.text\"\n    }\n  }\n]\n)",
        "result_count": 0,
        "note": "No match. Held customers have no live offer memory left."
      },
      {
        "db": "harbourline",
        "collection": "semantic",
        "operation": "find",
        "source": "memory",
        "label": "build_context · semantic memories for this customer",
        "mongosh": "db.semantic.find(\n{\n  \"user_id\": \"C-1001\"\n}\n)",
        "result_count": 2,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "episodic",
        "operation": "find",
        "source": "memory",
        "label": "build_context · episodic memories for this customer",
        "mongosh": "db.episodic.find(\n{\n  \"user_id\": \"C-1001\"\n}\n)",
        "result_count": 1,
        "note": null
      }
    ]
  },
  "procedural": {
    "title": "Fee-waiver procedure",
    "db": "harbourline",
    "queries": [
      {
        "db": "harbourline",
        "collection": "procedural",
        "operation": "find",
        "source": "memory",
        "label": "discover_procedures('late fee waiver')",
        "mongosh": "db.procedural.find(\n{\n  \"visibility\": \"org\",\n  \"$or\": [\n    {\n      \"procedure\": {\n        \"$regex\": \"late[- ]fee[- ]waiver\",\n        \"$options\": \"i\"\n      }\n    },\n    {\n      \"description\": {\n        \"$regex\": \"late[- ]fee[- ]waiver\",\n        \"$options\": \"i\"\n      }\n    },\n    {\n      \"content\": {\n        \"$regex\": \"late[- ]fee[- ]waiver\",\n        \"$options\": \"i\"\n      }\n    }\n  ]\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "procedural",
        "operation": "findOne",
        "source": "memory",
        "label": "get_procedure('late-fee-waiver', visibility='org')",
        "mongosh": "db.procedural.findOne(\n{\n  \"procedure\": \"late-fee-waiver\",\n  \"visibility\": \"org\"\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "customers",
        "operation": "findOne",
        "source": "bank",
        "label": "Tool check_fee_waiver_eligibility",
        "mongosh": "db.customers.findOne(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"_id\": 0\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "findOne",
        "source": "bank",
        "label": "Tool check_fee_waiver_eligibility",
        "mongosh": "db.accounts.findOne(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"_id\": 0\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "fee_waivers",
        "operation": "find",
        "source": "bank",
        "label": "Tool check_fee_waiver_eligibility",
        "mongosh": "db.fee_waivers.find(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"_id\": 0\n}\n).sort({\n  \"waived_on\": -1\n}).limit(1)",
        "result_count": 0,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "findOne",
        "source": "bank",
        "label": "Tool apply_fee_waiver",
        "mongosh": "db.accounts.findOne(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"_id\": 0\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "fee_waivers",
        "operation": "insertOne",
        "source": "bank",
        "label": "Tool apply_fee_waiver",
        "mongosh": "db.fee_waivers.insertOne(\n{\n  \"customer_id\": \"C-1001\",\n  \"amount_sgd\": 100.0,\n  \"reason_code\": \"LFW-01\",\n  \"waived_on\": \"2026-10-21\"\n}\n)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "accounts",
        "operation": "updateOne",
        "source": "bank",
        "label": "Tool apply_fee_waiver",
        "mongosh": "db.accounts.updateOne(\n{\n  \"customer_id\": \"C-1001\"\n},\n{\n  \"$set\": {\n    \"late_fee_sgd\": 0\n  }\n}\n)",
        "result_count": 1,
        "note": null
      }
    ]
  },
  "taxonomic": {
    "title": "Bank vocabulary",
    "db": "harbourline",
    "queries": [
      {
        "db": "harbourline",
        "collection": "disputes",
        "operation": "find",
        "source": "bank",
        "label": "Tool get_dispute_status",
        "mongosh": "db.disputes.find(\n{\n  \"customer_id\": \"C-1001\",\n  \"status\": {\n    \"$ne\": \"closed\"\n  }\n},\n{\n  \"_id\": 0\n}\n).sort({\n  \"opened\": -1\n}).limit(1)",
        "result_count": 1,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "taxonomic",
        "operation": "find",
        "source": "memory",
        "label": "search_taxonomic('provisional credit', domain='cards')",
        "mongosh": "db.taxonomic.find(\n{\n  \"domain\": \"cards\",\n  \"visibility\": \"org\",\n  \"term\": {\n    \"$regex\": \"provisional credit\",\n    \"$options\": \"i\"\n  }\n}\n)",
        "result_count": 1,
        "note": null
      }
    ]
  },
  "context": {
    "title": "Context assembly",
    "db": "harbourline",
    "queries": [
      {
        "db": "harbourline",
        "collection": "semantic",
        "operation": "find",
        "source": "memory",
        "label": "build_context · semantic memories for this customer",
        "mongosh": "db.semantic.find(\n{\n  \"user_id\": \"C-1001\"\n}\n)",
        "result_count": 2,
        "note": null
      },
      {
        "db": "harbourline",
        "collection": "episodic",
        "operation": "find",
        "source": "memory",
        "label": "build_context · episodic memories for this customer",
        "mongosh": "db.episodic.find(\n{\n  \"user_id\": \"C-1001\"\n}\n)",
        "result_count": 1,
        "note": null
      }
    ]
  }
}
/* QUERIES_END */;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }

  function meta(q) {
    var n = q.result_count;
    if (n == null) return q.operation === "watch" ? "registered" : "—";
    return n + (n === 1 ? " doc" : " docs");
  }

  function card(q) {
    return '<article class="mq-card">' +
      '<div class="mq-top">' +
        '<span class="mq-src ' + esc(q.source || "bank") + '">' + esc(q.source || "bank") + '</span>' +
        '<span class="mq-op">' + esc((q.db || "harbourline") + "." + q.collection + "." + q.operation + "()") + '</span>' +
        '<span class="mq-meta">' + esc(meta(q)) + '</span>' +
        '<button class="mq-copy" type="button">Copy</button>' +
      '</div>' +
      '<div class="mq-label">' + esc(q.label || "") + '</div>' +
      (q.note ? '<p class="mq-note">' + esc(q.note) + '</p>' : '') +
      '<pre class="mq-shell">' + esc(q.mongosh || "") + '</pre>' +
    '</article>';
  }

  function render(sceneId) {
    var root = document.getElementById("mongo-monitor");
    if (!root) return;
    var scene = CATALOG[sceneId];
    var title = scene ? scene.title : "Side B commands";
    var count = scene ? scene.queries.length : 0;
    var intro = '<p class="mq-intro">Commands this scene sends on Side B, in order. Paste any of them into <b>mongosh</b>. Bank data is <b>harbourline</b>. Memory sits in that same database, which is what makes the fraud-scene <b>$lookup</b> possible.</p>';
    var list = scene
      ? scene.queries.map(card).join("")
      : '<p class="mq-intro">Open a scene. The commands for that scene show up here, next to the story.</p>';
    root.innerHTML =
      '<div class="mongo-head"><div><h2>MongoDB</h2>' +
      '<div class="mongo-sub">harbourline' + (scene ? " · " + esc(title) : "") + '</div></div>' +
      (count ? '<span class="mongo-count">' + count + '</span>' : '') +
      '</div><div class="mongo-body">' + intro + list + '</div>';
  }

  function mount() {
    var root = document.getElementById("mongo-monitor");
    if (!root || root.dataset.bound) return;
    root.dataset.bound = "1";
    root.addEventListener("click", function (e) {
      var btn = e.target.closest && e.target.closest(".mq-copy");
      if (!btn) return;
      var text = btn.closest(".mq-card").querySelector(".mq-shell").textContent;
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = "Copy"; }, 1200);
      });
    });
  }

  global.MongoMonitor = {
    show: function (sceneId) { mount(); render(sceneId); },
    catalog: CATALOG
  };
})(window);
