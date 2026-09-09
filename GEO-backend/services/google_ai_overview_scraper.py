import os
import time
import random
import re
import csv
from datetime import datetime
from typing import List, Dict, Any
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

def setup_driver():
    """Setup Chrome driver with stealth settings (works on Linux/GCP headless servers)"""
    import platform
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    ]
    
    is_linux = platform.system() == "Linux"
    
    opts = webdriver.ChromeOptions()
    opts.add_argument(f'--user-agent={random.choice(user_agents)}')
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--disable-popup-blocking")
    
    # Headless + sandbox flags required for Linux servers (GCP, etc.)
    if is_linux:
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-setuid-sandbox")
        opts.add_argument("--window-size=1920,1080")
        opts.binary_location = "/usr/bin/google-chrome"
        print("🕵️ Headless mode FORCED (Linux/GCP detection)")
    else:
        opts.add_argument("--start-maximized")


    
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option('useAutomationExtension', False)
    
    # Try to use system chromedriver or specify path
    selenium_url = os.environ.get('SELENIUM_URL')
    
    if selenium_url:
        try:
            print(f"🌐 Connecting to Remote Selenium at: {selenium_url}")
            driver = webdriver.Remote(
                command_executor=selenium_url,
                options=opts
            )
            return driver
        except Exception as e:
            print(f"❌ Failed to connect to Remote Selenium: {e}")
            print("Falling back to local driver...")

    # Local driver - try system-installed first, then common paths
    try:
        driver = webdriver.Chrome(options=opts)
    except Exception:
        if is_linux:
            # Linux paths
            linux_paths = ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"]
            driver = None
            for path in linux_paths:
                try:
                    service = Service(executable_path=path)
                    driver = webdriver.Chrome(service=service, options=opts)
                    print(f"  ✅ Using chromedriver at: {path}")
                    break
                except Exception:
                    continue
            if not driver:
                raise RuntimeError(
                    "Chrome/ChromeDriver not found on this Linux server. "
                    "Install with: sudo apt install -y google-chrome-stable chromium-chromedriver"
                )
        else:
            # Windows paths
            try:
                service = Service(executable_path="chromedriver.exe")
                driver = webdriver.Chrome(service=service, options=opts)
            except Exception:
                service = Service(executable_path="drivers/chromedriver.exe")
                driver = webdriver.Chrome(service=service, options=opts)
    
    # Enhanced stealth JS overrides via CDP
    try:
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            '''
        })
    except Exception as e:
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def wait_for_ai_overview(driver, timeout=10):
    """Wait for AI Overview section to appear and load"""
    try:
        # Wait for potential AI Overview indicators
        wait = WebDriverWait(driver, timeout)
        
        # Try multiple strategies to detect AI Overview loading
        ai_overview_selectors = [
            "div[data-attrid*='GenerativeAnswer']",
            "div[data-hveid] div:contains('AI Overview')",
            "div[jsname]",  # Generic container that might hold AI Overview
        ]
        
        # Wait a bit for dynamic content to load
        time.sleep(3)
        
        # Scroll to trigger lazy loading
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(2)
        
        # Scroll more to ensure full content loads
        driver.execute_script("window.scrollTo(0, 800);")
        time.sleep(2)
        
        return True
        
    except Exception as e:
        print(f"⏱️ Timeout waiting for AI Overview: {str(e)}")
        return False


def click_show_more_button(driver):
    """Try to click 'Show more' button to expand AI Overview"""
    try:
        # Common patterns for "Show more" button
        show_more_patterns = [
            "//span[contains(text(), 'Show more')]",
            "//button[contains(text(), 'Show more')]",
            "//div[contains(text(), 'Show more')]",
            "//span[contains(text(), 'show more')]",
            "//*[contains(@aria-label, 'Show more')]",
            "//span[contains(@class, 'show-more')]"
        ]
        
        for pattern in show_more_patterns:
            try:
                show_more_btn = driver.find_element(By.XPATH, pattern)
                if show_more_btn.is_displayed():
                    driver.execute_script("arguments[0].scrollIntoView(true);", show_more_btn)
                    time.sleep(1)
                    driver.execute_script("arguments[0].click();", show_more_btn)
                    print(" ✅ Clicked 'Show more' button")
                    time.sleep(3)  # Wait after expanding
                    return True
            except:
                continue
        
        print("  ℹ️ No 'Show more' button found")
        return False
    except Exception as e:
        print(f"    ⚠️ Error clicking 'Show more': {str(e)}")
        return False


def extract_ai_overview_text(ai_section) -> str:
    """
    Extract clean AI Overview answer text
    Removes headers, UI elements, and sources section
    """
    try:
        text_content = ai_section.get_text(separator=' ', strip=True)

        # Robust noise removal: remove common UI and error fragments that appear
        # anywhere in the scraped text (not only at the start). This targets
        # messages like the one reported by the user such as:
        # "An AI Overview is not available for this search" and
        # "Can't generate an AI overview right now. Try again later." as well
        # as UI elements like "AI Overview", "Listen Pause", multilingual
        # variants and translation errors.
        # Initial strip to help anchors like '^' match correctly
        text_content = text_content.strip()

        noise_patterns = [
            r"An AI Overview is not available for this search",
            r"Can(?:'t| not) generate an AI overview right now(?:\.|)\s*Try again later(?:\.|)",
            r"^\s*AI Overview",        # heading / UI label
            r"^\s*Listen\s*Pause",
            r"^\s*सुनें\s*रोकें",
            r"^\s*English\b\s*",      # language toggle/label noise at start
            r"^\s*English\s+Hindi",    # multi-language toggle noise
            r"^\s*Hindi\b\s*",        # alternative language toggle
            r"Error translating content(?:\.|).*?Please try again later(?:\.|)",
            r"Can't generate an right now", # defensive/typo variants
        ]

        for pattern in noise_patterns:
            text_content = re.sub(pattern, '', text_content, flags=re.IGNORECASE | re.DOTALL)
            text_content = text_content.strip()
        
        # Find where sources section starts
        sources_pattern = r'(?:Sources|Citations|References)\s*:'
        sources_match = re.search(sources_pattern, text_content, re.IGNORECASE)
        
        if sources_match:
            answer_part = text_content[:sources_match.start()]
        else:
            # If no clear sources section, look for URL pattern
            url_pattern = r'\n\s*https?://'
            url_match = re.search(url_pattern, text_content)
            if url_match:
                answer_part = text_content[:url_match.start()]
            else:
                answer_part = text_content
        
        answer_part = answer_part.strip()
        
        # Remove trailing UI elements
        trailing_patterns = [
            r'\s+Learn more\s*$',
            r'\s+Show more\s*$',
            r'\s+Feedback\s*$',
            r'\s+View all\s*$',
            r'\s+See more\s*$',
        ]
        
        for pattern in trailing_patterns:
            answer_part = re.sub(pattern, '', answer_part, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        answer_part = re.sub(r'\s+', ' ', answer_part).strip()
        
        # Limit to 4500 characters, cut at last sentence
        if len(answer_part) > 4500:
            truncated = answer_part[:4500]
            last_period = truncated.rfind('.')
            if last_period > 500:
                answer_part = truncated[:last_period + 1]
            else:
                answer_part = truncated + "..."
        
        return answer_part
    
    except Exception as e:
        print(f"Error extracting AI Overview text: {str(e)}")
        return ""


def extract_ai_overview_links(driver, query: str, max_links: int = 10) -> Dict[str, Any]:
    """
    Search Google and extract answer text + citation links from AI Overview
    """
    result = {
        'answer_text': '',
        'links': [],
        'has_ai_overview': False
    }
    
    try:
        from urllib.parse import quote_plus
        encoded_query = quote_plus(query)
        search_url = f"https://www.google.com/search?q={encoded_query}&hl=en&gl=us"
        print(f"Searching via direct SERP URL: {search_url}")
        
        driver.get(search_url)
        time.sleep(random.uniform(4, 6))
        
        # If redirected to consent page or search failed, try typing manually
        if "consent.google.com" in driver.current_url:
            try:
                reject_btn = driver.find_element(By.XPATH, "//*[contains(text(), 'Reject all')]")
                reject_btn.click()
                time.sleep(2)
            except:
                pass
        
        print("Waiting for AI Overview to load...")
        wait_for_ai_overview(driver, timeout=10)
        
        click_show_more_button(driver)
        
        driver.execute_script("window.scrollTo(0, 1000);")
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        page_size = len(driver.page_source)
        if page_size < 12000:
            print(f"  ⚠️ Degraded page detected ({page_size:,} bytes) — Google may have served a stripped response for this UA")
        
        ai_section = None
        
        # Strategy 1: Find by "AI Overview" or "AI overview" heading
        ai_heading = soup.find(string=lambda text: text and ('AI Overview' in text or 'AI overview' in text) if text else False)
        if ai_heading:
            parent = ai_heading.find_parent('div', {'data-hveid': True})
            if not parent:
                parent = ai_heading.find_parent('div', {'data-attrid': True})
            if not parent:
                parent = ai_heading.find_parent('div')
                for _ in range(7):
                    if parent and len(parent.get_text(strip=True)) > 150:
                        break
                    parent = parent.find_parent('div') if parent else None
            
            ai_section = parent
            if ai_section:
                print("  ✅ Found AI Overview (by heading)")
        
        # Strategy 2: Find by modern Google Generative/Overview DOM classes & attributes
        if not ai_section:
            generative_divs = soup.find_all('div', attrs={
                'data-attrid': lambda x: x and ('Generative' in str(x) or 'ai_overview' in str(x).lower()) if x else False
            })
            if not generative_divs:
                # Common Google AI Overview container classes: MNNufe, K3n31, etc.
                generative_divs = soup.find_all('div', class_=lambda c: c and ('MNNufe' in str(c) or 'K3n31' in str(c)) if c else False)
                
            if generative_divs:
                ai_section = generative_divs[0]
                print("  ✅ Found AI Overview (by Generative attribute/class)")
        
        # Strategy 3: Find by jscontroller/data-initq containers with substantial text
        if not ai_section:
            candidate_divs = soup.find_all('div', attrs={'data-hveid': True})
            for div in candidate_divs:
                text_content = div.get_text(strip=True)
                links_in_div = div.find_all('a', href=True)
                if len(text_content) > 200 and len(links_in_div) >= 1:
                    if 'Generative' in str(div) or 'Overview' in text_content or 'AI' in text_content or 'Listen' in text_content:
                        ai_section = div
                        print("  ✅ Found AI Overview (by candidate container)")
                        break
        
        # Strategy 4: Fallback - grab top SERP block with multiple references
        if not ai_section:
            hveid_divs = soup.find_all('div', {'data-hveid': True})
            for div in hveid_divs:
                text_content = div.get_text(strip=True)
                links_in_div = div.find_all('a', href=True)
                if len(text_content) > 300 and len(links_in_div) >= 2:
                    ai_section = div
                    print("  ✅ Found AI Overview (by fallback content)")
                    break
        
        if not ai_section:
            print("  ℹ️ AI Overview not found on page")
            return result
        
        result['has_ai_overview'] = True


        
        # Extract clean answer text
        answer_text = extract_ai_overview_text(ai_section)
        result['answer_text'] = answer_text
        
        if answer_text:
            print(f"Extracted answer text ({len(answer_text)} characters)")
        
        # Extract citation links
        citation_links = ai_section.find_all('a', {
            'target': '_blank',
            'rel': 'noopener',
            'href': True
        })
        
        if not citation_links:
            citation_links = ai_section.find_all('a', href=True)
        
        print(f"Found {len(citation_links)} potential citation links")
        
        seen_urls = set()
        
        for link in citation_links:
            if len(result['links']) >= max_links:
                break
            
            href = link.get('href', '')
            
            # Remove text fragments from URL
            clean_url = re.sub(r'#:~:text=.*$', '', href)
            
            # Filter: only external links
            if (href.startswith('http') and 
                'google.com' not in href and
                'youtube.com' not in href and
                '/search?' not in href and
                clean_url not in seen_urls):
                
                seen_urls.add(clean_url)
                
                # Get link title
                title = link.get_text(strip=True)
                if not title or len(title) < 3:
                    aria_label = link.get('aria-label', '')
                    if aria_label:
                        title = aria_label
                    else:
                        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', href)
                        title = domain_match.group(1) if domain_match else 'Source'
                
                result['links'].append({
                    'position': len(result['links']) + 1,
                    'title': title[:150],
                    'url': clean_url
                })
        
        if result['links']:
            print(f"Extracted {len(result['links'])} citation URLs")
        
    except Exception as e:
        print(f"Error during extraction: {str(e)}")
        import traceback
        traceback.print_exc()
    
    return result


def scrape_google_ai_overview(prompts: List[str], brand_name: str, max_links_per_prompt: int = 10) -> Dict[str, Any]:
    """
    Scrape Google AI Overview for multiple prompts
    
    Args:
        prompts: List of search prompts
        brand_name: Brand name for file naming
        max_links_per_prompt: Maximum links to extract per prompt
    
    Returns:
        Dictionary with results and CSV filename
    """
    print("\n" + "="*80)
    print("🎯 GOOGLE AI OVERVIEW SCRAPING")
    print("="*80 + "\n")
    
    driver = None
    all_results = []
    
    try:
        # Setup driver
        print("🚀 Initializing Chrome driver...")
        driver = setup_driver()
        print("✅ Driver ready\n")
        
        # Process each prompt
        for idx, prompt in enumerate(prompts, 1):
            print(f"[{idx}/{len(prompts)}] Processing prompt:")
            
            # Extract links AND answer text
            extraction_result = extract_ai_overview_links(driver, prompt, max_links_per_prompt)
            
            # Store results
            prompt_result = {
                'prompt_index': idx,
                'prompt': prompt,
                'has_ai_overview': extraction_result['has_ai_overview'],
                'answer_text': extraction_result['answer_text'],
                'num_links': len(extraction_result['links']),
                'links': extraction_result['links']
            }
            all_results.append(prompt_result)
            
            # Random delay between queries to avoid detection
            if idx < len(prompts):
                delay = random.uniform(5, 8)  # Increased delay
                print(f"    ⏳ Waiting {delay:.1f}s before next query...\n")
                time.sleep(delay)
        
    except Exception as e:
        print(f"\n❌ Error during scraping: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        if driver:
            driver.quit()
            print("\n✔ Browser closed")
    
    # Generate CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"{brand_name.replace(' ', '_')}_google_ai_overview_{timestamp}.csv"
    
    print(f"\n💾 Saving results to CSV: {csv_filename}")
    save_results_to_csv(all_results, csv_filename)
    
    # Summary
    prompts_with_ai = sum(1 for r in all_results if r['has_ai_overview'])
    total_links = sum(r['num_links'] for r in all_results)
    
    print(f"\n{'='*80}")
    print(f"📊 SCRAPING COMPLETE")
    print(f"{'='*80}")
    print(f"Total Prompts: {len(prompts)}")
    print(f"Prompts with AI Overview: {prompts_with_ai}")
    print(f"Total Links Extracted: {total_links}")
    print(f"Average Links per Prompt: {total_links/len(prompts):.1f}")
    print(f"CSV File: {csv_filename}")
    print(f"{'='*80}\n")
    
    return {
        'results': all_results,
        'csv_filename': csv_filename,
        'total_prompts': len(prompts),
        'prompts_with_ai_overview': prompts_with_ai,
        'total_links': total_links
    }


def save_results_to_csv(results: List[Dict[str, Any]], filename: str):
    """Save scraping results to CSV file with answer text"""
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow([
                'Prompt Index', 
                'Prompt', 
                'Has AI Overview',
                'AI Overview Answer',
                'Link Position', 
                'Link Title', 
                'URL'
            ])
            
            # Write data
            for result in results:
                prompt_idx = result['prompt_index']
                prompt = result['prompt']
                has_ai = 'Yes' if result['has_ai_overview'] else 'No'
                answer = result['answer_text']
                
                if result['links']:
                    for link in result['links']:
                        writer.writerow([
                            prompt_idx,
                            prompt,
                            has_ai,
                            answer,
                            link['position'],
                            link['title'],
                            link['url']
                        ])
                else:
                    # Write row even if no links found
                    writer.writerow([
                        prompt_idx, 
                        prompt, 
                        has_ai,
                        answer if answer else 'No AI Overview found',
                        'N/A', 
                        'No links found', 
                        'N/A'
                    ])
        
        print(f"    ✅ CSV file saved successfully")
    
    except Exception as e:
        print(f"    ❌ Error saving CSV: {str(e)}")


def analyze_ai_overview_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze the scraped results to generate insights"""
    total_prompts = len(results)
    prompts_with_ai = sum(1 for r in results if r['has_ai_overview'])
    prompts_with_links = sum(1 for r in results if r['num_links'] > 0)
    total_links = sum(r['num_links'] for r in results)
    
    # Calculate average answer length
    answer_lengths = [len(r['answer_text']) for r in results if r['answer_text']]
    avg_answer_length = sum(answer_lengths) / len(answer_lengths) if answer_lengths else 0
    
    # Get unique domains
    all_domains = []
    for result in results:
        for link in result['links']:
            domain_match = re.search(r'https?://(?:www\.)?([^/]+)', link['url'])
            if domain_match:
                all_domains.append(domain_match.group(1))
    
    from collections import Counter
    domain_counts = Counter(all_domains)
    top_domains = domain_counts.most_common(10)
    
    analysis = {
        'total_prompts': total_prompts,
        'prompts_with_ai_overview': prompts_with_ai,
        'prompts_with_links': prompts_with_links,
        'ai_overview_rate': (prompts_with_ai / total_prompts * 100) if total_prompts > 0 else 0,
        'total_citations': total_links,
        'avg_citations_per_prompt': total_links / total_prompts if total_prompts > 0 else 0,
        'avg_answer_length': round(avg_answer_length, 0),
        'top_cited_domains': top_domains,
        'unique_domains': len(set(all_domains))
    }
    
    return analysis
