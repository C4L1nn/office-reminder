"""Shared GIB parser — used by build-time importer and runtime sync.

Ensures single source of truth for mapping/normalization.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

PARSER_VERSION = "2.0.0-real-gib-faz3"

EDEFTER_MAP = {
    "AYLIK_GELIR": "Aylık Yükleme Tercihinde Bulunmuş Gelir Vergisi",
    "AYLIK_DIGER": "Aylık Yükleme Tercihinde Bulunmuş Diğer",
    "GECICI_GELIR": "Geçici Vergi Dönemleri Bazında Yükleme Tercihinde Bulunmuş Gelir Vergisi",
    "GECICI_DIGER": "Geçici Vergi Dönemleri Bazında Yükleme Tercihinde Bulunmuş Diğer",
}


def map_obligation(raw: dict[str, Any]) -> str | None:
    tax = (raw.get("taxType") or "").strip()
    subject = (raw.get("subject") or "").strip()
    title = (raw.get("title") or "").strip()
    desc = (raw.get("description") or "").strip()

    if "Muhtasar ve Prim Hizmet Beyannamesi" in desc:
        return "GIB_MUHSGK"

    if tax == "Vergi Usul Kanunu" and subject == "Berat" and "Elektronik Defter" in title:
        if EDEFTER_MAP["AYLIK_GELIR"] in desc:
            return "GIB_EDEFTER_AYLIK_GELIR"
        if EDEFTER_MAP["AYLIK_DIGER"] in desc:
            return "GIB_EDEFTER_AYLIK_DIGER"
        if EDEFTER_MAP["GECICI_GELIR"] in desc:
            return "GIB_EDEFTER_GECICI_GELIR"
        if EDEFTER_MAP["GECICI_DIGER"] in desc:
            return "GIB_EDEFTER_GECICI_DIGER"
        return "GIB_VUK_GENEL"

    direct = {
        "Katma Değer Vergisi": "GIB_KDV",
        "Damga Vergisi": "GIB_DAMGA",
        "Kurum Geçici Vergisi": "GIB_GECICI_KURUMLAR",
        "Kurumlar Vergisi": "GIB_KURUMLAR",
        "Motorlu Taşıtlar Vergisi": "GIB_MTV",
        "Özel Tüketim Vergisi": "GIB_OZEL_TUKETIM",
        "Eğlence Vergisi": "GIB_EGLENCE",
        "Harçlar Kanunu": "GIB_HARCLAR",
        "Türkiye Turizm Tanıtım ve Geliştirme Ajansı Hakkında Kanun": "GIB_TURIZM",
        "Gelir Vergisi": "GIB_GELIR_VERGISI",
        "Veraset ve İntikal Vergisi": "GIB_VERASET",
        "Noterlerce Tahsil Edilen Vergi Resim ve Harçlar ile Değerli Kağıt Bedelleri": "GIB_NOTER",
        "Banka ve Sigorta Muameleleri Vergisi": "GIB_BSMV",
        "Özel İletişim Vergisi": "GIB_OIV",
        "Kaynak Kullanımını Destekleme Fonu": "GIB_KKDF",
        "Kaynak Kullanımını Destekleme Fonu ": "GIB_KKDF",
        "Şans Oyunları Vergisi": "GIB_SANS",
        "Elektrik ve Havagazı Tüketim Vergisi": "GIB_ELEKTRIK",
        "İlan ve Reklam Vergisi": "GIB_ILAN",
        "Yangın Sigortası Vergisi": "GIB_YANGIN",
        "Konaklama Vergisi": "GIB_KONAKLAMA",
        "7440 Sayılı Kanun": "GIB_7440",
        "Haberleşme Vergisi": "GIB_HABERLESME",
        "Dijital Hizmet Vergisi": "GIB_DIJITAL",
        "Çevre Kanunu,Vergi Usul Kanunu": "GIB_CEVRE_VUK",
        "Gelir Geçici Vergisi": "GIB_GELIR_GECICI",
        "Değerli Konut Vergisi": "GIB_DEGERLI_KONUT",
        "Yerel Asgari Tamamlayıcı Kurumlar Vergisi": "GIB_YEREL_ASGARI",
        "Küresel Asgari Tamamlayıcı Kurumlar Vergisi": "GIB_KURESEL_ASGARI",
        "Çevre Temizlik Vergisi": "GIB_CEVRE_TEMIZLIK",
        "Emlak Vergisi": "GIB_EMLAK",
        "Vergi Usul Kanunu": "GIB_VUK_BILDIRIM",
        "Gelir Vergisi,Kurumlar Vergisi": "GIB_MUHSGK",
    }
    clean_tax = tax.strip()
    if clean_tax in direct:
        return direct[clean_tax]
    return None
