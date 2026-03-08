"""
LangChain Agent for filtering agricultural land offers from LeBonCoin.
Uses Azure OpenAI GPT-5.2 for filtering based on criteria.
"""

import os
import smtplib
import yaml
from pathlib import Path

from email.mime.text import MIMEText
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel
from typing import Optional

import lbc

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()


# Pydantic models for structured output
class FilterResult(BaseModel):
    """Model for the filter result from LLM."""
    matches: bool
    url: str = ""
    summary: str = ""


class FilteredAd(BaseModel):
    """Model for a filtered ad with price info."""
    url: str
    summary: str
    price: Optional[int] = None
    surface: Optional[int] = None
    price_per_hectare: Optional[float] = None


def load_config(yaml_path: str) -> dict:
    """Load cities and recipients from YAML file."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_ad_id(url: str) -> str:
    """Extract the ad ID from the URL (last segment of the path)."""
    return url.rstrip("/").split("/")[-1]


def extract_land_surface(ad) -> Optional[int]:
    """Extract land_plot_surface from ad attributes."""
    if not hasattr(ad, 'attributes') or not ad.attributes:
        return None
    for attr in ad.attributes:
        if attr.key == "land_plot_surface":
            try:
                return int(attr.value)
            except (ValueError, TypeError):
                return None
    return None


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


def create_filter_prompt(url: str, subject: str, body: str) -> str:
    """Create the filtering prompt for Azure OpenAI."""
    return f"""Tu es un agent qui doit filtrer des annonces de vente de propriétés à partir de la description du bien.
Tu ne dois retenir que les annonces qui parlent explicitement de terrains dédiés à l'agriculture ou à la foresterie. S'il n'est pas fait mention de surface utilisable pour ces activités, ne retiens pas l'annonce.
Les annonces doivent parler de terres agricoles, des forêts, des bois, des champs, des prés, des pâturages.
La surface doit être d'au moins 10 hectares.

Retourne un JSON avec:
- "matches": true ou false selon si l'annonce correspond aux critères
- "url": l'URL de l'annonce (copie la valeur ci-dessous)
- "summary": un résumé en une ligne de la propriété pour l'aspect terre agricole (vide si matches=false)

URL: {url}
Subject: {subject}
Body: {body}
"""


def filter_ad(llm: AzureChatOpenAI, ad) -> Optional[FilteredAd]:
    """Filter an ad using Azure OpenAI."""
    prompt = create_filter_prompt(
        url=ad.url,
        subject=ad.subject,
        body=ad.body or ""
    )

    structured_llm = llm.with_structured_output(FilterResult)
    result: FilterResult = structured_llm.invoke(prompt)

    if not result.matches:
        return None

    # Extract price and surface info
    price = None
    if ad.price:
        if isinstance(ad.price, (list, tuple)):
            price = ad.price[0] if ad.price else None
        else:
            price = ad.price
    surface = extract_land_surface(ad)

    # Calculate price per hectare (surface is in m², 1 hectare = 10000 m²)
    price_per_hectare = None
    if price and surface and surface > 0:
        price_per_hectare = (price / surface) * 10000

    return FilteredAd(
        url=result.url or ad.url,
        summary=result.summary,
        price=price,
        surface=surface,
        price_per_hectare=price_per_hectare
    )


def format_number_fr(value: float, decimals: int = 0) -> str:
    """Format number with French locale (space as thousand sep, comma as decimal sep)."""
    if decimals > 0:
        formatted = f"{value:,.{decimals}f}"
    else:
        formatted = f"{value:,.0f}"
    return formatted.replace(",", " ").replace(".", ",")


def generate_html(ads_by_city: dict[str, list[FilteredAd]]) -> str:
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
    <p>Aucune annonce correspondant aux critères n'a été trouvée.</p>
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
            if ad.price_per_hectare:
                price_line = f'<p class="price-info">{format_number_fr(ad.price)} EUR - {format_number_fr(ad.surface)} m² - {format_number_fr(ad.price_per_hectare)} EUR/ha</p>'
            elif ad.price:
                price_line = f'<p class="price-info">{format_number_fr(ad.price)} EUR</p>'

            ads_html += f"""
            <div class="offer">
                <h3><a href="{ad.url}" target="_blank">{ad.summary.split('.')[0] if ad.summary else 'Offre'}</a></h3>
                {price_line}
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
        .offer p {{
            margin: 0;
            color: #5f6360;
            line-height: 1.6;
            font-size: 0.95em;
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
        <p class="subtitle">{total_ads} annonce(s) de terres agricoles correspondant aux critères</p>
    </div>
    {sections_html}
    <div class="footer">
        <p>Agent de veille - <a href="https://www.printempsdesterres.fr/">printempsdesterres.fr</a></p>
    </div>
</body>
</html>
"""


def send_email(
    html_content: str,
    recipients: list[str],
    sender_email: str = "agent.leboncoin@equancy.ai"
):
    """Send the HTML email via SMTP."""
    sender_username = os.environ.get("SMTP_USERNAME")
    sender_password = os.environ.get("SMTP_PASSWORD")

    if not sender_username or not sender_password:
        raise ValueError("SMTP_USERNAME and SMTP_PASSWORD environment variables must be set")

    msg = MIMEText(html_content, "html")
    msg["Subject"] = "Annonces de terres agricoles - LeBonCoin"
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = "herve.mignot@equancy.com"

    with smtplib.SMTP_SSL("smtp.tem.scaleway.com", 465) as server:
        server.login(sender_username, sender_password)
        server.sendmail(sender_email, recipients, msg.as_string())

    print(f"Email sent successfully to {recipients}")


def main():
    """Main function to run the agent."""
    # Load configuration
    config_path = Path(__file__).parent / "cities.yaml"
    config = load_config(config_path)
    cities = config["cities"]

    # Get recipients from environment variable (comma-separated)
    recipients_env = os.environ.get("RECIPIENTS", "")
    if not recipients_env:
        raise ValueError("RECIPIENTS environment variable must be set")
    recipients = [email.strip() for email in recipients_env.split(",")]

    # Initialize Azure OpenAI LLM
    llm = AzureChatOpenAI(
        azure_deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        #temperature=0,
    )

    # Collect filtered ads by city
    ads_by_city: dict[str, list[FilteredAd]] = {}

    # Track processed ad IDs to avoid duplicates
    processed_ad_ids: set[str] = set()

    # Process each city
    for city in cities:
        city_name = city["name"]
        lat = city["lat"]
        lng = city["lng"]
        radius = city.get("radius", 50_000)

        print(f"Searching in {city_name} (radius: {radius}m)...")
        ads_by_city[city_name] = []

        try:
            ads = search_city(city_name, lat, lng, radius)
            print(f"  Found {len(ads)} ads")

            for ad in ads:
                ad_id = extract_ad_id(ad.url)

                if ad_id in processed_ad_ids:
                    print(f"  Skipping (already processed): {ad.subject[:50]}...")
                    continue

                processed_ad_ids.add(ad_id)
                print(f"  Processing: {ad.subject[:50]}...")

                try:
                    filtered = filter_ad(llm, ad)

                    if filtered:
                        print(f"    -> Matched! {filtered.summary[:50]}...")
                        ads_by_city[city_name].append(filtered)
                    else:
                        print(f"    -> Did not match criteria")
                except Exception as e:
                    print(f"    -> Error processing ad {ad_id}: {e}")
                    continue

        except Exception as e:
            print(f"  Error searching {city_name}: {e}")
            continue

    total_ads = sum(len(ads) for ads in ads_by_city.values())
    print(f"\nTotal matching ads: {total_ads}")

    # Generate HTML
    html_content = generate_html(ads_by_city)

    # Send email
    if os.environ.get("SEND_EMAIL", 0):
        try:
            send_email(html_content, recipients)
        except Exception as e:
            print(f"Error sending email: {e}")
            # Save HTML locally as fallback
            with open("outputs/results.html", "w", encoding="utf-8") as f:
                f.write(html_content)
            print("HTML saved to results.html")
    else:
        with open("outputs/results.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("HTML saved to results.html")


if __name__ == "__main__":
    main()
