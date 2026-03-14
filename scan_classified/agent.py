"""
LangChain Agent for filtering agricultural land offers from LeBonCoin.
Uses Azure OpenAI GPT-5.2 for filtering based on criteria.
"""

import os
import smtplib
import warnings
from pathlib import Path

from email.mime.text import MIMEText
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel
from typing import Optional

import lbc
from .utils import (
    load_config,
    extract_ad_id,
    extract_land_surface,
    extract_tenure,
    format_number_fr,
)
from .history import (
    SeenAd,
    load_seen_ads,
    save_seen_ads,
    load_seen_ads_gist,
    save_seen_ads_gist,
    discard_old_ads,
    should_call_llm,
    should_email,
)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Suppress Pydantic serialization warning from LangChain structured output
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")


# Pydantic models for structured output
class FilterResult(BaseModel):
    """Model for the filter result from LLM."""
    matches: bool
    url: str = ""
    summary: str = ""
    tags: list[str] = []
    reason: str = ""


class FilteredAd(BaseModel):
    """Model for a filtered ad with price info."""
    url: str
    summary: str
    price: Optional[int] = None
    surface: Optional[int] = None
    price_per_hectare: Optional[float] = None
    tenure: Optional[str] = None
    tags: list[str] = []


def search_city(city_name: str, lat: float, lng: float, radius: int = 50_000) -> list:
    """Search for agricultural land offers in a city."""
    client = lbc.Client()

    location = lbc.City(
        lat=lat,
        lng=lng,
        radius=radius,
        city=city_name
    )

    result = client.search(
        text="terre agricole",
        locations=[location],
        page=1,
        limit=35,
        sort=lbc.Sort.NEWEST,
        ad_type=lbc.AdType.OFFER,
        category=lbc.Category.IMMOBILIER,
    )

    return result.ads


OLD_PROMPT_TEMPLATE = """Tu es un agent qui doit filtrer des annonces de vente de propriétés à partir de la description du bien.
Tu ne dois retenir que les annonces qui parlent explicitement de terrains dédiés à l'agriculture ou à la foresterie. S'il n'est pas fait mention de surface utilisable pour ces activités, ne retiens pas l'annonce.
Les annonces doivent parler de terres agricoles, de biens agricoles, de forêts, de bois, de champs cultivés ou à cultiver, de prés, de pâturages.
La surface doit être d'au moins 10 hectares, soit 100000 m2.

Extrais de l'annonce les caractéristiques suivantes, qui constitueront la liste "tags" de la propriété:
- 'bio': les terrains sont certifiés bio
- 'forêt': les terrains comportent une partie boisée signalée comme telle
- 'eau': il est fait mention de lac, d'étang, de rivière ou de point d'eau sur le terrain
- 'bâtiment': il est fait mention de bâtiment pouvant être utilisé pour l'exploitation agricole

Attention, certaines offres sont en fait des recherches de terrain, des demandes et PAS des propositions.
Il faut donc les filtrer.

Retourne un JSON avec:
- "matches": true ou false selon si l'annonce correspond aux critères
- "url": l'URL de l'annonce (copie la valeur ci-dessous)
- "summary": un résumé en une ligne de la propriété pour l'aspect terre agricole (vide si matches=false)
- "tags": une liste de tags des caractéristiques de la propriété
- "reason": la justification en une locution du rejet de l'annonce ('ok' if matches=true)

URL: {url}
Subject: {subject}
Surface: {surface} m2
Body: {body}
"""

# Bump this when PROMPT_TEMPLATE changes to force re-evaluation of all seen ads
PROMPT_VERSION = 1

PROMPT_TEMPLATE = """Tu es un agent chargé de filtrer des annonces de vente de propriétés à partir des informations fournies.

Ta mission est de déterminer si l'annonce correspond à une PROPOSITION DE VENTE d'un bien comprenant explicitement des terres agricoles ou forestières exploitables.

Ne retiens l'annonce que si toutes les conditions suivantes sont remplies :
1. Il s'agit bien d'une offre de vente, et non d'une recherche, d'une demande, d'un mandat de prospection ou d'un acquéreur qui cherche un bien.
2. L'annonce mentionne explicitement des surfaces de terres dédiées ou utilisables pour l'agriculture ou la foresterie.
3. Ces surfaces concernent des terres agricoles, biens agricoles, forêts, bois, champs cultivés ou à cultiver, prés, pâturages ou prairies.
4. La surface pertinente pour ces usages est d'au moins 10 hectares, soit 100000 m2.

Règles importantes :
- Ne retiens pas les annonces qui ne mentionnent qu'un “grand terrain”, une “propriété rurale”, un “domaine”, un “cadre naturel”, un “parc” ou un “terrain” sans mention explicite d'usage agricole ou forestier.
- Ne retiens pas les annonces où seule la surface totale du bien est connue, sans indication claire que cette surface correspond à des terres agricoles ou forestières exploitables.
- Ne retiens pas les annonces où les surfaces agricoles ou forestières exploitables sont inférieures à 100000 m2, même si la surface totale du bien est supérieure.
- Si l'annonce évoque seulement un potentiel agricole, un cadre champêtre, des chevaux, la chasse ou les loisirs, sans mention explicite de terres agricoles ou forestières exploitables, alors rejects l'annonce.
- Le champ “Surface” est prioritaire pour la surface totale fournie. Le texte du sujet et du corps peut servir à confirmer ou préciser la nature agricole ou forestière des surfaces. En cas de contradiction, base-toi sur l'information la plus explicite concernant les surfaces agricoles ou forestières réellement exploitables.
- En cas de doute, sois strict : retourne matches=false.

Extrais aussi les tags suivants si, et seulement si, ils sont explicitement mentionnés :
- “bio” : les terrains sont certifiés bio ou l'exploitation est explicitement certifiée bio
- “forêt” : la propriété comprend une partie boisée, une forêt ou des bois situés sur le terrain
- “eau” : la propriété comprend sur son terrain un lac, un étang, une rivière, un ruisseau, une source ou un point d'eau
- “bâtiment” : la propriété comprend un bâtiment utilisable pour l'exploitation agricole (grange, hangar, stabulation, bergerie, bâtiment agricole, dépendance d'exploitation, etc.). Une simple maison d'habitation ne suffit pas.

Tu dois retourner uniquement un JSON valide, sans commentaire ni texte additionnel, au format exact suivant :
{{
  “matches”: true|false,
  “url”: “...”,
  “summary”: “...”,
  “tags”: [“...”],
  “reason”: “...”
}}

Contraintes de sortie :
- “url” doit recopier exactement la valeur fournie dans l'entrée.
- Si matches=false, alors :
  - “summary” doit être une chaîne vide
  - “tags” doit être une liste vide
  - “reason” doit être une locution courte parmi :
    “annonce de recherche”
    “usage non explicite”
    “surface insuffisante”
    “surface agricole absente”
    “usage non agricole”
    “informations insuffisantes”
- Si matches=true, alors :
  - “summary” doit être une phrase courte, factuelle, sur l'aspect agricole ou forestier du bien
  - “tags” ne doit contenir que des tags parmi [“bio”, “forêt”, “eau”, “bâtiment”]
  - “reason” doit valoir “ok”

Entrée :
URL: {url}
Subject: {subject}
Surface: {surface} m2
Body: {body}
"""

def create_filter_prompt(url: str, subject: str, body: str, surface: int) -> str:
    """Create the filtering prompt for Azure OpenAI."""
    return PROMPT_TEMPLATE.format(
        url=url,
        subject=subject,
        surface=surface,
        body=body
    )


def filter_ad(llm: AzureChatOpenAI, ad) -> tuple[Optional[FilteredAd], str]:
    """Filter an ad using Azure OpenAI."""
    prompt = create_filter_prompt(
        url=ad.url,
        subject=ad.subject,
        surface=extract_land_surface(ad),
        body=ad.body or ""
    )

    structured_llm = llm.with_structured_output(FilterResult)
    result: FilterResult = structured_llm.invoke(prompt)
    
    if not result.matches:
        return None, result.reason or "Ne correspond pas aux critères"

    # Extract price and surface info
    price = None
    if ad.price:
        if isinstance(ad.price, (list, tuple)):
            price = ad.price[0] if ad.price else None
        else:
            price = ad.price
    surface = extract_land_surface(ad)

    # Filter out ads with less than 10 ha (100,000 m²)
    if not surface or surface < 100_000:
        return None, "Surface < 10 ha"

    tenure = extract_tenure(ad)

    # Calculate price per hectare (surface is in m², 1 hectare = 10000 m²)
    price_per_hectare = None
    if price and surface and surface > 0:
        price_per_hectare = (price / surface) * 10000

    return FilteredAd(
        url=result.url or ad.url,
        summary=result.summary,
        price=price,
        surface=surface,
        price_per_hectare=price_per_hectare,
        tenure=tenure,
        tags=result.tags
    ), 'ok'


def generate_html(ads_by_city: dict[str, list[FilteredAd]], total_processed: int, cooldown_days: int, discard_threshold_days: int) -> str:
    """Generate HTML content for the email, grouped by city."""
    total_ads = sum(len(ads) for ads in ads_by_city.values())

    if total_ads == 0:
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
    </style>
</head>
<body>
    <h1>Recherche de terres agricoles</h1>
    <p>Aucune nouvelle annonce correspondant aux critères n'a été trouvée.</p>
</body>
</html>
"""

    sections_html = ""
    for city_name, ads in ads_by_city.items():
        if not ads:
            continue

        ads_html = ""
        for ad in ads:
            price_line = ""
            tenure_str = f" - {ad.tenure}" if ad.tenure else ""
            surface_ha = ad.surface / 10_000 if ad.surface else None
            if ad.price_per_hectare and surface_ha:
                price_line = f'<p class="price-info">{format_number_fr(ad.price)} EUR - {format_number_fr(surface_ha, 1)} ha - {format_number_fr(ad.price_per_hectare)} EUR/ha{tenure_str}</p>'
            elif ad.price:
                price_line = f'<p class="price-info">{format_number_fr(ad.price)} EUR{tenure_str}</p>'

            tags_line = ""
            if ad.tags:
                tags_html = " ".join(f'<span class="tag">{tag}</span>' for tag in ad.tags)
                tags_line = f'<p class="tags">{tags_html}</p>'

            ads_html += f"""
            <div class="offer">
                <h3><a href="{ad.url}" target="_blank">{ad.summary if ad.summary else 'Offre'}</a></h3>
                {price_line}
                {tags_line}
                <p>{ad.summary}</p>
            </div>
"""

        sections_html += f"""
        <section class="city-section">
            <h2>{city_name} - {len(ads)} annonce(s)</h2>
            {ads_html}
        </section>
"""

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f8f9f7;
            color: #080808;
        }}
        .header {{
            background-color: #067790;
            color: white;
            padding: 25px 30px;
            border-radius: 8px;
            margin-bottom: 25px;
        }}
        .header h1 {{
            margin: 0;
            font-size: 1.8em;
            font-weight: 600;
        }}
        .header .subtitle {{
            margin: 8px 0 0 0;
            opacity: 0.9;
            font-size: 0.95em;
        }}
        h2 {{
            color: #067790;
            border-bottom: 3px solid #E8CB7A;
            padding-bottom: 8px;
            margin-top: 30px;
            margin-bottom: 15px;
            font-weight: 600;
        }}
        .city-section {{
            margin-bottom: 30px;
        }}
        .offer {{
            background-color: white;
            border-radius: 6px;
            padding: 18px 22px;
            margin-bottom: 12px;
            border-left: 4px solid #E8CB7A;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        }}
        .offer h3 {{
            margin: 0 0 8px 0;
            font-size: 1.05em;
            font-weight: 600;
        }}
        .offer h3 a {{
            color: #067790;
            text-decoration: none;
        }}
        .offer h3 a:hover {{
            text-decoration: underline;
            color: #055a6d;
        }}
        .offer .price-info {{
            font-size: 0.85em;
            color: #5f6360;
            background-color: #f0efe8;
            padding: 4px 10px;
            border-radius: 4px;
            display: inline-block;
            margin: 5px 0 10px 0;
            font-weight: 500;
        }}
        .offer .tags {{
            margin: 0 0 10px 0;
        }}
        .offer .tag {{
            display: inline-block;
            background-color: #fdf6e3;
            color: #5a5548;
            font-size: 0.8em;
            padding: 4px 12px;
            border: 1px solid #E8CB7A;
            border-radius: 15px;
            margin-right: 8px;
            font-weight: 500;
        }}
        .offer p {{
            margin: 0;
            color: #5f6360;
            line-height: 1.6;
            font-size: 0.95em;
        }}
        .info {{
            margin-top: 30px;
            padding: 15px 20px;
            background-color: #f0efe8;
            border-radius: 6px;
            font-size: 0.9em;
            color: #5f6360;
        }}
        .info h2 {{
            font-size: 1em;
            margin: 0 0 8px 0;
            color: #5f6360;
            border: none;
        }}
        .info ul {{
            margin: 0;
            padding-left: 20px;
        }}
        .info li {{
            margin-bottom: 4px;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #5f6360;
            font-size: 0.85em;
        }}
        .footer a {{
            color: #067790;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Printemps des Terres</h1>
        <p class="subtitle">{total_ads} annonce(s) de terres agricoles correspondant aux critères ({total_processed} annonces traitées)</p>
    </div>
    {sections_html}
    <div class="info">
        <h2>Informations</h2>
        <ul>
            <li>Les annonces sont représentées au bout de {cooldown_days} jours.</li>
            <li>Les annonces mémorisées et non vues sur le site depuis {discard_threshold_days} jours sont retirées des archives.</li>
        </ul>
    </div>
    <div class="footer">
        <p>Agent de veille - <a href="https://www.printempsdesterres.fr/">printempsdesterres.fr</a></p>
    </div>
</body>
</html>
"""


def send_email(html_content: str, recipients: list[str], sender_email: str, reply_to: str = None):
    """Send the HTML email via SMTP."""
    smtp_host = os.environ.get("SMTP_HOST")
    sender_username = os.environ.get("SMTP_USERNAME")
    sender_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_host or not sender_username or not sender_password:
        raise ValueError("SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD environment variables must be set")

    msg = MIMEText(html_content, "html")
    msg["Subject"] = "Annonces de terres agricoles - LeBonCoin"
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    if reply_to:
        msg["Reply-To"] = reply_to

    with smtplib.SMTP_SSL(smtp_host, 465) as server:
        server.login(sender_username, sender_password)
        server.sendmail(sender_email, recipients, msg.as_string())

    print(f"Email sent successfully to {recipients}")


def main():
    """Main function to run the agent."""
    from datetime import datetime, timezone

    # Load configuration
    config_path = Path(__file__).parent / "cities.yaml"
    config = load_config(config_path)
    cities = config["cities"]
    cooldown_days = config.get("cooldown_days", 30)
    discard_threshold_days = config.get("discard_threshold_days", 30 * 6)

    # Load seen ads (Gist backend if configured, local file otherwise)
    gist_id = os.environ.get("GIST_ID")
    github_token = os.environ.get("GITHUB_TOKEN")
    use_gist = bool(gist_id and github_token)

    if use_gist:
        seen_ads = load_seen_ads_gist(gist_id, github_token)
    else:
        seen_ads_path = Path(__file__).parent / "seen_ads.json"
        seen_ads = load_seen_ads(seen_ads_path)
    print(f"Loaded {len(seen_ads)} previously seen ads" + (" from gist" if use_gist else ""))

    # Discard ads not seen for too long
    seen_ads = discard_old_ads(seen_ads, discard_threshold_days)

    # Get recipients from environment variable (comma-separated)
    sender_email = os.environ.get("SENDER")
    reply_to = os.environ.get("REPLY_TO")
    recipients_env = os.environ.get("RECIPIENTS")
    if not recipients_env or not sender_email:
        raise ValueError("RECIPIENTS and SENDER environment variable must be set")

    recipients = [email.strip() for email in recipients_env.split(",")]

    # Initialize Azure OpenAI LLM
    llm = AzureChatOpenAI(
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        #temperature=0,
    )

    # Collect filtered ads by city (only ads that should be emailed)
    ads_by_city: dict[str, list[FilteredAd]] = {}

    # Track processed ad IDs to avoid duplicates within this run
    processed_ad_ids: set[str] = set()
    now = datetime.now(timezone.utc)

    # Process each city
    for city in cities:
        city_name = city["name"]
        lat = city["lat"]
        lng = city["lng"]
        radius = city.get("radius", 50_000)

        print(f"Searching in {city_name} (radius: {radius / 1_000:.2f} km)...")
        ads_by_city[city_name] = []

        try:
            ads = search_city(city_name, lat, lng, radius)
            print(f"  Found {len(ads)} ads")

            for ad in ads:
                ad_id = extract_ad_id(ad.url)

                if ad_id in processed_ad_ids:
                    print(f"  Skipping (already processed this run): {ad.subject[:50]}...")
                    continue

                processed_ad_ids.add(ad_id)

                # Update date_lastseen for existing ads
                if ad_id in seen_ads:
                    seen_ads[ad_id].date_lastseen = now

                # Decide whether to call the LLM
                if should_call_llm(ad_id, seen_ads, PROMPT_VERSION):
                    print(f"  Processing: {ad.subject[:50]}... {ad.url}")
                    try:
                        filtered, reason = filter_ad(llm, ad)
                        matched = filtered is not None

                        # Create or update seen ad entry
                        seen_ads[ad_id] = SeenAd(
                            ad_id=ad_id,
                            date_added=seen_ads[ad_id].date_added if ad_id in seen_ads else now,
                            date_lastseen=now,
                            matched=matched,
                            reason=reason,
                            version_matched=PROMPT_VERSION,
                            date_emailed=seen_ads[ad_id].date_emailed if ad_id in seen_ads else None,
                            city=city_name,
                        )

                        if filtered and should_email(seen_ads[ad_id], cooldown_days):
                            if seen_ads[ad_id].date_emailed is not None:
                                filtered.tags.append("déjà vue")
                            print(f"    -> Matched! {filtered.summary[:50]}...")
                            ads_by_city[city_name].append(filtered)
                        elif filtered:
                            print(f"    -> Matched but already emailed recently")
                        else:
                            print(f"    -> Did not match criteria ({reason})")
                    except Exception as e:
                        print(f"    -> Error processing ad {ad_id}: {e}")
                        continue
                else:
                    seen_ad = seen_ads[ad_id]
                    if seen_ad.matched and should_email(seen_ad, cooldown_days):
                        # Re-build FilteredAd from the live ad data for the email
                        print(f"  Re-including (cooldown expired): {ad.subject[:50]}...")
                        try:
                            filtered, _ = filter_ad(llm, ad)
                            if filtered:
                                filtered.tags.append("déjà vue")
                                ads_by_city[city_name].append(filtered)
                        except Exception as e:
                            print(f"    -> Error re-processing ad {ad_id}: {e}")
                    else:
                        print(f"  Skipping (already seen, v{seen_ad.version_matched}): {ad.subject[:50]}...")

        except Exception as e:
            print(f"  Error searching {city_name}: {e}")
            continue

    total_ads = sum(len(ads) for ads in ads_by_city.values())
    print(f"\nTotal ads to email: {total_ads}")

    # Mark emailed ads
    if total_ads > 0:
        for city_ads in ads_by_city.values():
            for ad in city_ads:
                ad_id = extract_ad_id(ad.url)
                if ad_id in seen_ads:
                    seen_ads[ad_id].date_emailed = now

    # Generate HTML
    html_content = generate_html(ads_by_city, len(processed_ad_ids), cooldown_days, discard_threshold_days)

    # Send email
    if os.environ.get("SEND_EMAIL", 0):
        try:
            send_email(html_content, recipients, sender_email, reply_to)
        except Exception as e:
            print(f"Error sending email: {e}")
            with open("outputs/results.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("HTML saved to results.html")
    else:
        with open("outputs/results.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("HTML saved to results.html")

    # Save seen ads
    if use_gist:
        save_seen_ads_gist(gist_id, github_token, seen_ads)
        print(f"Saved {len(seen_ads)} seen ads to Gist {gist_id}")
    else:
        save_seen_ads(seen_ads_path, seen_ads)
        print(f"Saved {len(seen_ads)} seen ads to {seen_ads_path}")


if __name__ == "__main__":
    main()
