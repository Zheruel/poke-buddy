import requests
from bs4 import BeautifulSoup
import json
import logging
import time
import argparse
from typing import Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PokemonCardScraper:
    def __init__(self, test_mode: bool = False, prismatic_evolutions: bool = False):
        self.base_url = "https://pkmncards.com"
        self.cards_data = []
        self.test_mode = test_mode
        self.prismatic_evolutions = prismatic_evolutions
        self.seen_texts = set()  # Track seen card texts to avoid duplicates
        
    def get_page_content(self, url: str) -> Optional[BeautifulSoup]:
        try:
            response = requests.get(url)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except requests.RequestException as e:
            logger.error(f"Error fetching page {url}: {e}")
            return None

    def get_total_pages(self, soup: BeautifulSoup) -> int:
        try:
            last_page_link = soup.find('span', class_='last-page-link')
            if not last_page_link:
                return 1
            
            # Extract the number from the text that looks like "/ 41"
            total_pages = int(last_page_link.text.strip().split('/')[-1])
            return total_pages
        except (AttributeError, ValueError) as e:
            logger.error(f"Error getting total pages: {e}")
            return 1

    def parse_energy_symbols(self, text: str) -> list:
        """Convert energy symbol text like '{C}{C}' into a list of energy types ['Colorless', 'Colorless']"""
        energy_map = {
            'C': 'Colorless',
            'G': 'Grass',
            'R': 'Fire',
            'W': 'Water',
            'L': 'Lightning',
            'P': 'Psychic',
            'F': 'Fighting',
            'D': 'Darkness',
            'M': 'Metal',
            'Y': 'Fairy',
            'N': 'Dragon'
        }
        
        energy_symbols = []
        # Find all energy symbols between { }
        parts = text.split('{')
        for part in parts[1:]:  # Skip first part before any {
            if '}' in part:
                symbol = part[0]  # Get the letter between { and }
                if symbol in energy_map:
                    energy_symbols.append(energy_map[symbol])
        return energy_symbols

    def parse_single_energy(self, text: str) -> str:
        """Convert a single energy symbol to its full name"""
        try:
            symbols = self.parse_energy_symbols(text)
            if not symbols:
                logger.warning(f"No energy symbol found in text: {text}")
                return "Colorless"  # Default to Colorless if no energy type found
            return symbols[0]
        except Exception as e:
            logger.error(f"Error parsing single energy from text '{text}': {e}")
            return "Colorless"  # Default to Colorless on error

    def parse_attack(self, attack_text: str) -> Dict:
        """Parse an attack text into structured data"""
        try:
            # Split into energy cost and attack info
            parts = attack_text.split('→')
            if len(parts) != 2:
                return {}
                
            energy_cost_text = parts[0].strip()
            attack_info = parts[1].strip()
            
            # Parse attack name and damage
            name = ""
            damage = "0"
            description = ""
            
            # Split attack info into lines
            info_lines = attack_info.split('\n')
            first_line = info_lines[0].strip()
            
            # Check if there's a damage value (number followed by × or just a number)
            if '×' in first_line:
                # Handle attacks with multipliers
                name_parts = first_line.split('×', 1)
                name = name_parts[0].rsplit(' ', 1)[0].strip()
                damage = name_parts[0].rsplit(' ', 1)[1].strip()
                if len(info_lines) > 1:
                    description = '\n'.join(info_lines[1:]).strip()
            elif ':' in first_line:
                # Handle attacks with descriptions
                name_and_damage, desc = first_line.split(':', 1)
                name_parts = name_and_damage.rsplit(' ', 1)
                if len(name_parts) == 2 and any(c.isdigit() for c in name_parts[1]):
                    name = name_parts[0].strip()
                    damage = name_parts[1].strip()
                else:
                    name = name_and_damage.strip()
                description = (desc + '\n' + '\n'.join(info_lines[1:])).strip()
            else:
                # Handle attacks without explicit damage markers
                name_parts = first_line.rsplit(' ', 1)
                if len(name_parts) == 2 and any(c.isdigit() for c in name_parts[1]):
                    name = name_parts[0].strip()
                    damage = name_parts[1].strip()
                else:
                    name = first_line.strip()
                if len(info_lines) > 1:
                    description = '\n'.join(info_lines[1:]).strip()
            
            # Clean up damage value - extract only numbers
            damage = ''.join(filter(str.isdigit, damage)) or "0"
            
            return {
                "name": name,
                "damage": damage,
                "energy_cost": self.parse_energy_symbols(energy_cost_text),
                "description": description
            }
        except Exception as e:
            logger.error(f"Error parsing attack text '{attack_text}': {e}")
            return {}

    def parse_card_data(self, card: BeautifulSoup) -> Dict:
        """Parse a card's data, saving raw text content instead of parsed structures"""
        try:
            # Get the complete text content first to check for duplicates
            text_div = card.find('div', class_='text')
            text_content = ""
            if text_div:
                # Preserve the text with its original formatting
                text_parts = []
                for p in text_div.find_all('p'):
                    text_parts.append(p.text.strip())
                text_content = "\n\n".join(text_parts)
            
            # Get name for logging purposes
            name = card.find('span', class_='name').text.strip()
            
            # Create a unique identifier from the card's text and type info
            type_div = card.find('div', class_='type-evolves-is')
            type_text = type_div.text.strip() if type_div else ""
            
            # Combine text content and type info for duplicate detection
            card_identifier = f"{type_text}\n{text_content}"
            
            # Skip if we've already seen this card text
            if card_identifier in self.seen_texts:
                logger.info(f"Skipping duplicate card: {name}")
                return {}
            
            # Initialize card data
            card_data = {
                "name": name,
            }
            
            # Get type and category info
            if type_div:
                card_data["type_line"] = type_text
                
                # Basic category determination
                type_info = type_text.split('›')[0].strip()
                card_data["category"] = type_info
                
                # Check if this is a Pokémon card
                is_pokemon = "Pokémon" in type_info
            else:
                is_pokemon = False
            
            # Get HP if present (only for Pokémon cards)
            if is_pokemon:
                hp_span = card.find('span', class_='hp')
                if hp_span:
                    card_data["hp"] = int(hp_span.text.strip().replace('HP', '').strip())
            
            # Get color/energy type if present
            color_span = card.find('span', class_='color')
            if color_span:
                card_data["color"] = color_span.text.strip()
            
            # Store the text content
            card_data["text"] = text_content
            
            # Get retreat cost only for Pokémon cards
            if is_pokemon:
                try:
                    stats_div = card.find('div', class_='weak-resist-retreat')
                    if stats_div:
                        retreat_span = stats_div.find('span', class_='retreat')
                        if retreat_span and retreat_span.find('abbr'):
                            retreat_text = retreat_span.find('abbr')['title']
                            retreat_cost = len(retreat_text.split('{C}')) - 1
                            card_data["retreat_cost"] = retreat_cost
                        else:
                            card_data["retreat_cost"] = 0
                    else:
                        card_data["retreat_cost"] = 0
                except Exception as e:
                    logger.error(f"Error parsing retreat cost for {name}: {e}")
                    card_data["retreat_cost"] = 0
            
            # Add card text to seen set
            self.seen_texts.add(card_identifier)
            return card_data
            
        except Exception as e:
            logger.error(f"Error parsing card data for {name if 'name' in locals() else 'unknown card'}: {e}")
            return {}

    def scrape_cards(self):
        if self.prismatic_evolutions:
            start_url = f"{self.base_url}/?s=set%3Apre&sort=date&ord=auto&display=text"
        else:
            start_url = f"{self.base_url}/page/1/?s=format%3Af-on-standard-2025&sort=date&ord=auto&display=text"
        
        # Get first page and total pages
        soup = self.get_page_content(start_url)
        if not soup:
            return
        
        total_pages = 1 if self.test_mode else self.get_total_pages(soup)
        logger.info(f"Found {total_pages} pages to scrape{' (test mode)' if self.test_mode else ''}")

        for page in range(1, total_pages + 1):
            logger.info(f"Scraping page {page}/{total_pages}")
            
            if page > 1:
                if self.prismatic_evolutions:
                    url = f"{self.base_url}/page/{page}/?s=set%3Apre&sort=date&ord=auto&display=text"
                else:
                    url = f"{self.base_url}/page/{page}/?s=format%3Af-on-standard-2025&sort=date&ord=auto&display=text"
                soup = self.get_page_content(url)
                if not soup:
                    continue

            # Find all card articles on the page
            cards = soup.find_all('article', class_='type-pkmn_card')
            
            for card in cards:
                card_data = self.parse_card_data(card)
                if card_data:
                    self.cards_data.append(card_data)
            
            # Be nice to the server
            time.sleep(1)

    def save_to_json(self, filename: str = 'pokemon_cards.json'):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.cards_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Successfully saved {len(self.cards_data)} cards to {filename}")
        except Exception as e:
            logger.error(f"Error saving to JSON file: {e}")

def main():
    parser = argparse.ArgumentParser(description='Scrape Pokemon cards from pkmncards.com')
    parser.add_argument('--test', action='store_true', help='Run in test mode (only scrape first page)')
    parser.add_argument('--prismatic-evolutions', action='store_true', help='Scrape cards from the Prismatic Evolutions set')
    args = parser.parse_args()

    scraper = PokemonCardScraper(test_mode=args.test, prismatic_evolutions=args.prismatic_evolutions)
    scraper.scrape_cards()
    scraper.save_to_json()

if __name__ == "__main__":
    main()
