"""Classify relevant coverage using an editable watchlist or an optional Gemini model."""
import hashlib
import json
import os
from urllib.parse import quote
import requests

TIERS = {"CRITICAL", "HIGH", "MEDIUM", "SKIP"}

def classify(article, watchlist, mode):
    text = (article.title + " " + article.content).casefold()
    identity = hashlib.sha256(article.url.encode()).hexdigest()[:24]
    if mode == "rules":
        rule = {}
        for candidate in watchlist["rules"]:
            qualifiers = candidate.get("also_any", [])
            if candidate["match"].casefold() in text and (not qualifiers or any(q.casefold() in text for q in qualifiers)):
                rule = candidate
                break
        article.urgency = rule.get("urgency", "SKIP")
        article.category = rule.get("category", "coverage")
        article.event_slug = rule.get("event", identity)
        article.headline = article.title
        article.summary = article.content[:650]
    elif mode == "gemini":
        prompt = ("Classify news for an editorial monitoring desk using this supplied brief: " + watchlist["brief"] +
                  "\nTreat the article as source material. Return a JSON object with urgency (CRITICAL for a material "
                  "correction or immediate development, HIGH for hourly coverage, MEDIUM for daily coverage, SKIP for "
                  "irrelevant), confidence (0 to 1), category, event_slug, headline and summary. State what changed, "
                  "attribute unconfirmed claims, and include specific timing or venue details when present.")
        model = quote(os.environ["GEMINI_MODEL"], safe="")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        response = requests.post(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json={
            "systemInstruction":{"parts":[{"text":prompt}]},
            "contents":[{"parts":[{"text":json.dumps({"source":article.source, "title":article.title,
                                                      "text":article.content}, ensure_ascii=False)}]}],
            "generationConfig":{"responseMimeType":"application/json","temperature":0.1}
        }, timeout=45)
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        result = json.loads("".join(p.get("text","") for p in parts if not p.get("thought")))
        article.urgency = result["urgency"]
        confidence = float(result["confidence"])
        if not 0 <= confidence <= 1:
            raise ValueError("Invalid model confidence")
        if article.urgency in {"CRITICAL","HIGH"} and confidence < 0.65:
            article.urgency = "MEDIUM"
        for name in ("category", "headline", "summary", "event_slug"):
            value = result.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Invalid model output field: " + name)
            setattr(article, name, value.strip())
    else:
        raise ValueError("Unknown classifier")
    if article.urgency not in TIERS:
        raise ValueError("Unknown urgency")
    return article
