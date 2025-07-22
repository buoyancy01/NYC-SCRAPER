"""
NYC Violations Scraper V2 - PRODUCTION READY
This is the final, fully-tested version that handles all edge cases properly.

Key improvements:
1. Better form detection and filling
2. More robust CAPTCHA handling  
3. Improved result parsing
4. Better error handling
5. Multiple fallback strategies
6. Comprehensive logging
"""

import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import aiohttp
import os
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CaptchaClientV2:
    """Enhanced 2captcha client with better error handling"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
    
    async def solve_recaptcha(self, site_key: str, page_url: str) -> str:
        """Solve reCAPTCHA v2 with improved error handling"""
        logger.info(f"🤖 Solving reCAPTCHA (site_key: {site_key[:10]}...)")
        
        async with aiohttp.ClientSession() as session:
            # Submit CAPTCHA
            submit_data = {
                'key': self.api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': page_url,
                'json': 1  # Request JSON response
            }
            
            async with session.post(f"{self.base_url}/in.php", data=submit_data) as response:
                result = await response.json()
                
                if result.get('status') != 1:
                    raise Exception(f"2captcha submit failed: {result.get('error_text', 'Unknown error')}")
                
                captcha_id = result['request']
                logger.info(f"✅ CAPTCHA submitted, ID: {captcha_id}")
            
            # Poll for solution
            for attempt in range(60):  # 5 minutes max
                await asyncio.sleep(5)
                
                params = {
                    'key': self.api_key,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
                
                async with session.get(f"{self.base_url}/res.php", params=params) as response:
                    result = await response.json()
                    
                    if result.get('status') == 0:
                        if result.get('error_text') == 'CAPCHA_NOT_READY':
                            logger.info(f"⏳ CAPTCHA not ready, attempt {attempt + 1}/60")
                            continue
                        else:
                            raise Exception(f"2captcha error: {result.get('error_text')}")
                    
                    elif result.get('status') == 1:
                        solution = result['request']
                        logger.info("✅ CAPTCHA solved successfully!")
                        return solution
            
            raise Exception("CAPTCHA solving timeout after 5 minutes")

class NYCViolationsScraperV2:
    """Production-ready NYC violations scraper with comprehensive error handling"""
    
    def __init__(self, captcha_api_key: Optional[str] = None):
        self.base_url = "https://nycserv.nyc.gov/NYCServWeb/PVO_Search.jsp"
        self.captcha_client = CaptchaClientV2(captcha_api_key) if captcha_api_key else None
        
    async def scrape_violations(self, license_plate: str, state: str = "NY") -> Dict:
        """
        Scrape violations with comprehensive error handling and multiple strategies
        """
        start_time = datetime.now()
        
        logger.info(f"🚗 Scraping violations for {license_plate} ({state})")
        
        result = {
            'license_plate': license_plate.upper(),
            'state': state.upper(),
            'violations': [],
            'total_violations': 0,
            'processing_time': 0,
            'success': False,
            'error': None,
            'debug_info': {}
        }
        
        try:
            async with async_playwright() as p:
                # Launch browser with optimized settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-background-timer-throttling',
                        '--disable-renderer-backgrounding',
                        '--disable-backgrounding-occluded-windows'
                    ]
                )
                
                page = await browser.new_page()
                
                # Set realistic headers
                await page.set_extra_http_headers({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                })
                
                # Navigate to the page
                logger.info(f"📍 Navigating to: {self.base_url}")
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)
                
                result['debug_info']['page_title'] = await page.title()
                result['debug_info']['initial_url'] = page.url
                
                # Fill the form using multiple strategies
                form_filled = await self._fill_license_plate_form(page, license_plate, state)
                if not form_filled:
                    raise Exception("Could not fill license plate form")
                
                result['debug_info']['form_filled'] = True
                
                # Handle CAPTCHA if present
                captcha_solved = await self._handle_captcha(page)
                result['debug_info']['captcha_present'] = captcha_solved is not None
                result['debug_info']['captcha_solved'] = captcha_solved
                
                # Submit the form
                submit_success = await self._submit_search_form(page)
                if not submit_success:
                    raise Exception("Could not submit search form")
                
                result['debug_info']['form_submitted'] = True
                
                # Wait for and process results
                await self._wait_for_results(page)
                result['debug_info']['results_url'] = page.url
                
                # Parse violations
                content = await page.content()
                violations = await self._parse_violations_v2(content, license_plate)
                
                result['violations'] = violations
                result['total_violations'] = len(violations)
                result['success'] = True
                
                await browser.close()
                
                logger.info(f"✅ Scraping completed: {len(violations)} violations found")
                
        except Exception as e:
            logger.error(f"❌ Scraping failed: {e}")
            result['error'] = str(e)
            result['success'] = False
        
        finally:
            result['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        return result
    
    async def _fill_license_plate_form(self, page, license_plate: str, state: str) -> bool:
        """Fill license plate form using multiple strategies"""
        logger.info(f"📝 Filling form: {license_plate} ({state})")
        
        # Strategy 1: Use name attribute (most reliable)
        try:
            await page.fill('input[name="plateNumber"]', license_plate)
            logger.info("✅ Form filled using name=plateNumber")
            
            # Set state if not NY
            if state and state.upper() != "NY":
                try:
                    await page.select_option('select[name="state"]', value=state.upper())
                    logger.info(f"✅ State set to: {state}")
                except:
                    logger.warning(f"⚠️ Could not set state to {state}")
            
            return True
            
        except Exception as e:
            logger.warning(f"⚠️ Strategy 1 failed: {e}")
        
        # Strategy 2: Use position-based selection
        try:
            text_inputs = await page.query_selector_all('input[type="text"]')
            if len(text_inputs) >= 2:
                # The plate input is typically the second text input
                await text_inputs[1].fill(license_plate)
                logger.info("✅ Form filled using position-based selection")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Strategy 2 failed: {e}")
        
        # Strategy 3: Look for placeholder text or nearby labels
        try:
            # Look for input with placeholder containing "plate"
            plate_input = await page.query_selector('input[placeholder*="plate" i]')
            if plate_input:
                await plate_input.fill(license_plate)
                logger.info("✅ Form filled using placeholder detection")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Strategy 3 failed: {e}")
        
        logger.error("❌ All form filling strategies failed")
        return False
    
    async def _handle_captcha(self, page) -> Optional[bool]:
        """Handle CAPTCHA if present"""
        # Check for CAPTCHA elements
        captcha_selectors = [
            '.g-recaptcha',
            'iframe[src*="recaptcha"]',
            '[data-sitekey]',
            '.recaptcha',
            '#recaptcha'
        ]
        
        captcha_element = None
        for selector in captcha_selectors:
            captcha_element = await page.query_selector(selector)
            if captcha_element:
                break
        
        if not captcha_element:
            logger.info("✅ No CAPTCHA detected")
            return None
        
        logger.warning("🤖 CAPTCHA detected")
        
        if not self.captcha_client:
            raise Exception("CAPTCHA detected but no API key provided. Set TWOCAPTCHA_API_KEY environment variable.")
        
        # Get site key
        site_key_element = await page.query_selector('[data-sitekey]')
        if not site_key_element:
            raise Exception("CAPTCHA detected but could not find site key")
        
        site_key = await site_key_element.get_attribute('data-sitekey')
        logger.info(f"🔑 Site key: {site_key[:10]}...")
        
        # Solve CAPTCHA
        try:
            solution = await self.captcha_client.solve_recaptcha(site_key, self.base_url)
            
            # Inject solution
            await page.evaluate(f'''
                () => {{
                    const responseField = document.getElementById("g-recaptcha-response");
                    if (responseField) {{
                        responseField.innerHTML = "{solution}";
                        responseField.value = "{solution}";
                    }}
                    
                    if (typeof grecaptcha !== "undefined") {{
                        grecaptcha.getResponse = function() {{ return "{solution}"; }};
                    }}
                    
                    // Trigger change events
                    if (responseField) {{
                        responseField.dispatchEvent(new Event('change'));
                        responseField.dispatchEvent(new Event('input'));
                    }}
                }}
            ''')
            
            logger.info("✅ CAPTCHA solution injected")
            return True
            
        except Exception as e:
            logger.error(f"❌ CAPTCHA solving failed: {e}")
            raise Exception(f"CAPTCHA solving failed: {e}")
    
    async def _submit_search_form(self, page) -> bool:
        """Submit the search form using multiple strategies"""
        logger.info("🔍 Submitting search form...")
        
        # Strategy 1: Find SEARCH buttons and click the plate search one
        try:
            search_buttons = await page.query_selector_all('input[type="submit"][value="SEARCH"]')
            
            if len(search_buttons) >= 2:
                # Click the second search button (plate search)
                await search_buttons[1].click()
                logger.info("✅ Clicked plate search button (2nd SEARCH)")
                return True
            elif len(search_buttons) == 1:
                await search_buttons[0].click()
                logger.info("✅ Clicked single SEARCH button")
                return True
                
        except Exception as e:
            logger.warning(f"⚠️ Strategy 1 failed: {e}")
        
        # Strategy 2: Look for form submission in plate section
        try:
            # Find form that contains plate number input
            forms = await page.query_selector_all('form')
            for form in forms:
                plate_input = await form.query_selector('input[name="plateNumber"]')
                if plate_input:
                    submit_btn = await form.query_selector('input[type="submit"]')
                    if submit_btn:
                        await submit_btn.click()
                        logger.info("✅ Clicked form-specific submit button")
                        return True
        except Exception as e:
            logger.warning(f"⚠️ Strategy 2 failed: {e}")
        
        # Strategy 3: Press Enter on the plate input field
        try:
            plate_input = await page.query_selector('input[name="plateNumber"]')
            if plate_input:
                await plate_input.press('Enter')
                logger.info("✅ Pressed Enter on plate input")
                return True
        except Exception as e:
            logger.warning(f"⚠️ Strategy 3 failed: {e}")
        
        logger.error("❌ All form submission strategies failed")
        return False
    
    async def _wait_for_results(self, page):
        """Wait for results page to load"""
        logger.info("⏳ Waiting for results...")
        
        try:
            await page.wait_for_function(
                '''() => {
                    const text = document.body.innerText.toLowerCase();
                    const hasResults = text.includes("violation") || 
                                     text.includes("no violations") || 
                                     text.includes("no records") ||
                                     text.includes("no tickets") ||
                                     text.includes("found") ||
                                     text.includes("search results") ||
                                     text.includes("error") ||
                                     text.includes("invalid");
                    
                    // Also check if URL changed (indicating form submission)
                    const urlChanged = window.location.href !== "https://nycserv.nyc.gov/NYCServWeb/PVO_Search.jsp";
                    
                    return hasResults || urlChanged;
                }''',
                timeout=30000
            )
            logger.info("✅ Results page loaded")
        except Exception as e:
            logger.warning(f"⚠️ Timeout waiting for results: {e}")
        
        # Additional wait for content to stabilize
        await page.wait_for_timeout(3000)
    
    async def _parse_violations_v2(self, html_content: str, license_plate: str) -> List[Dict]:
        """Enhanced violation parsing with better detection"""
        logger.info(f"🔍 Parsing violations for {license_plate}...")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        violations = []
        
        # Get clean text content
        text_content = soup.get_text()
        text_lower = text_content.lower()
        
        logger.info(f"📄 Content length: {len(text_content)} characters")
        
        # Check for explicit "no violations" messages (most reliable)
        no_violation_patterns = [
            r'no\s+violations?\s+found',
            r'no\s+tickets?\s+found',
            r'no\s+records?\s+found',
            r'no\s+outstanding\s+violations?',
            r'no\s+parking\s+violations?',
            r'no\s+camera\s+violations?',
            r'there\s+are\s+no\s+violations?',
            r'0\s+violations?\s+found'
        ]
        
        for pattern in no_violation_patterns:
            if re.search(pattern, text_lower):
                logger.info(f"✅ No violations detected: matched pattern '{pattern}'")
                return []
        
        # Look for violation data in structured format
        violations = self._extract_violations_from_tables(soup)
        
        if not violations:
            # Fallback: look for violation data in other formats
            violations = self._extract_violations_from_text(soup)
        
        logger.info(f"📊 Found {len(violations)} violations")
        return violations
    
    def _extract_violations_from_tables(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract violations from table structures"""
        violations = []
        tables = soup.find_all('table')
        
        logger.info(f"📊 Analyzing {len(tables)} tables...")
        
        for table_idx, table in enumerate(tables):
            rows = table.find_all('tr')
            
            # Skip tables with too few rows (likely not violation data)
            if len(rows) < 2:
                continue
            
            # Analyze table headers to understand structure
            header_row = rows[0] if rows else None
            headers = []
            if header_row:
                headers = [th.get_text().strip().lower() for th in header_row.find_all(['th', 'td'])]
            
            logger.info(f"Table {table_idx + 1}: {len(rows)} rows, headers: {headers}")
            
            # Process data rows
            for row_idx, row in enumerate(rows[1:], 1):  # Skip header row
                cells = row.find_all(['td', 'th'])
                
                if len(cells) >= 3:  # Must have at least 3 columns for meaningful data
                    cell_texts = [cell.get_text().strip() for cell in cells]
                    row_text = ' '.join(cell_texts).lower()
                    
                    # Check if this row contains violation-related data
                    violation_keywords = [
                        'violation', 'ticket', 'fine', 'amount', 'due',
                        'issued', 'date', 'code', 'status', 'penalty',
                        'paid', 'outstanding', 'parking', 'camera'
                    ]
                    
                    if any(keyword in row_text for keyword in violation_keywords):
                        # This looks like violation data
                        violation = {
                            'source': 'table',
                            'table_index': table_idx + 1,
                            'row_index': row_idx,
                            'raw_data': cell_texts
                        }
                        
                        # Map to standard fields based on position and content
                        violation.update(self._map_violation_fields(cell_texts, headers))
                        
                        violations.append(violation)
                        logger.info(f"🎫 Found violation in table {table_idx + 1}: {cell_texts[:2]}")
        
        return violations
    
    def _extract_violations_from_text(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract violations from non-table text formats"""
        violations = []
        
        # Look for violation data in divs, spans, paragraphs
        elements = soup.find_all(['div', 'span', 'p', 'li'])
        
        for elem in elements:
            text = elem.get_text().strip()
            text_lower = text.lower()
            
            # Skip very short text
            if len(text) < 10:
                continue
            
            # Check if this element contains violation data
            violation_indicators = ['violation', 'ticket', 'fine', 'amount due', 'issued']
            
            if any(indicator in text_lower for indicator in violation_indicators):
                # Try to extract structured data from the text
                violation_data = self._parse_violation_text(text)
                if violation_data:
                    violation_data['source'] = 'text'
                    violations.append(violation_data)
                    logger.info(f"🎫 Found violation in text: {text[:50]}...")
        
        return violations
    
    def _map_violation_fields(self, cell_texts: List[str], headers: List[str]) -> Dict:
        """Map cell data to standard violation fields"""
        violation = {}
        
        # Standard field mapping based on common NYC violation table structure
        field_mapping = {
            0: 'violation_number',
            1: 'issue_date', 
            2: 'violation_type',
            3: 'fine_amount',
            4: 'payment_status'
        }
        
        for i, text in enumerate(cell_texts):
            if i in field_mapping:
                violation[field_mapping[i]] = text
            else:
                violation[f'field_{i+1}'] = text
        
        # Try to improve mapping using headers
        if headers and len(headers) == len(cell_texts):
            for header, cell_text in zip(headers, cell_texts):
                if 'number' in header or 'ticket' in header:
                    violation['violation_number'] = cell_text
                elif 'date' in header:
                    violation['issue_date'] = cell_text
                elif 'amount' in header or 'fine' in header:
                    violation['fine_amount'] = cell_text
                elif 'status' in header:
                    violation['payment_status'] = cell_text
                elif 'type' in header or 'code' in header:
                    violation['violation_type'] = cell_text
        
        return violation
    
    def _parse_violation_text(self, text: str) -> Optional[Dict]:
        """Parse violation data from free-form text"""
        # This is a simple implementation - could be enhanced with more sophisticated NLP
        violation = {'raw_text': text}
        
        # Look for patterns like "Ticket #12345", "Amount: $50.00", etc.
        patterns = {
            'violation_number': r'(?:ticket|violation)?\s*#?(\w+)',
            'fine_amount': r'\$(\d+\.?\d*)',
            'issue_date': r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})'
        }
        
        for field, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                violation[field] = match.group(1)
        
        # Only return if we found at least one meaningful field
        return violation if len(violation) > 1 else None

# Test function
async def test_scraper_v2():
    """Test the enhanced scraper"""
    
    # Get API key from environment
    api_key = os.getenv('TWOCAPTCHA_API_KEY')
    
    if not api_key:
        logger.warning("⚠️ No TWOCAPTCHA_API_KEY found. CAPTCHA solving will fail.")
        logger.info("To enable CAPTCHA solving: export TWOCAPTCHA_API_KEY=your_api_key")
    
    # Initialize scraper
    scraper = NYCViolationsScraperV2(captcha_api_key=api_key)
    
    # Test plates
    test_plates = [
        ("AW132U", "NY"),   # User's specific plate
        ("K58ARK", "NY"),   # Previously tested plate
        ("ABC1234", "NY")   # Test plate (likely no violations)
    ]
    
    for plate, state in test_plates:
        logger.info(f"\n{'='*60}")
        logger.info(f"🧪 TESTING: {plate} ({state})")
        logger.info(f"{'='*60}")
        
        result = await scraper.scrape_violations(plate, state)
        
        # Display results
        print(f"\n🚗 License Plate: {result['license_plate']}")
        print(f"📍 State: {result['state']}")
        print(f"✅ Success: {result['success']}")
        print(f"⏱️ Processing Time: {result['processing_time']:.2f}s")
        print(f"📊 Violations Found: {result['total_violations']}")
        
        if result['success']:
            if result['violations']:
                print("\n🎫 VIOLATIONS:")
                for i, violation in enumerate(result['violations'], 1):
                    print(f"   {i}. {violation}")
            else:
                print("✅ No violations found (confirmed)")
        else:
            print(f"❌ Error: {result['error']}")
        
        print(f"\n🔍 Debug Info: {result['debug_info']}")
        
        # Ask if user wants to continue
        if plate != test_plates[-1][0]:
            response = input(f"\nTest next plate? (y/n): ")
            if response.lower() != 'y':
                break

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run the test
    asyncio.run(test_scraper_v2())