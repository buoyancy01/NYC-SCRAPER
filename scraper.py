import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import aiohttp

class NYCViolationScraper:
    def __init__(self, captcha_client=None):
        # CORRECT URL - Fixed!
        self.base_url = "https://nycserv.nyc.gov/NYCServWeb/PVO_Search.jsp"
        self.captcha_client = captcha_client
        
    async def scrape_violations(self, license_plate: str, state: str = "NY") -> dict:
        """Scrape violations with proper CAPTCHA handling"""
        start_time = datetime.now()
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Navigate to correct URL
                await page.goto(self.base_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                
                # Fill plate number in correct field
                plate_selector = 'input[name="plateNumber"]'
                await page.fill(plate_selector, license_plate)
                
                # Set state if not NY
                if state != "NY":
                    await page.select_option('select[name="state"]', state)
                
                # Handle CAPTCHA
                captcha_present = await page.query_selector('.g-recaptcha, iframe[src*="recaptcha"]')
                if captcha_present and self.captcha_client:
                    await self._solve_captcha(page)
                elif captcha_present:
                    raise Exception("CAPTCHA detected but no captcha_client provided")
                
                # Click the correct search button (plate search, not violation search)
                search_buttons = await page.query_selector_all('input[type="submit"][value="SEARCH"]')
                if len(search_buttons) >= 2:
                    await search_buttons[1].click()  # Second button is plate search
                else:
                    raise Exception("Could not find plate search button")
                
                # Wait for results
                await page.wait_for_function(
                    '() => document.body.innerText.includes("violation") || document.body.innerText.includes("No violations")',
                    timeout=15000
                )
                
                content = await page.content()
                await browser.close()
                
                # Parse results with enhanced logic
                violations = self._parse_violations_enhanced(content, license_plate)
                
                return {
                    'license_plate': license_plate,
                    'state': state,
                    'violations': violations,
                    'total_violations': len(violations),
                    'processing_time': (datetime.now() - start_time).total_seconds(),
                    'success': True
                }
                
        except Exception as e:
            return {
                'license_plate': license_plate,
                'state': state,
                'error': str(e),
                'success': False,
                'processing_time': (datetime.now() - start_time).total_seconds()
            }
    
    async def _solve_captcha(self, page):
        """Solve CAPTCHA using 2captcha service"""
        if not self.captcha_client:
            raise Exception("No captcha client configured")
            
        # Get site key from reCAPTCHA
        site_key_element = await page.query_selector('[data-sitekey]')
        if not site_key_element:
            raise Exception("Could not find reCAPTCHA site key")
            
        site_key = await site_key_element.get_attribute('data-sitekey')
        
        # Solve CAPTCHA
        solution = await self.captcha_client.solve_recaptcha(
            site_key=site_key,
            page_url=self.base_url
        )
        
        # Inject solution
        await page.evaluate(f'document.getElementById("g-recaptcha-response").innerHTML = "{solution}";')
        await page.evaluate('if (typeof grecaptcha !== "undefined") grecaptcha.getResponse = function() { return "' + solution + '"; };')
    
    def _parse_violations_enhanced(self, html_content: str, license_plate: str) -> list:
        """Enhanced parsing that properly detects violations vs no violations"""
        soup = BeautifulSoup(html_content, 'html.parser')
        violations = []
        
        text_content = soup.get_text().lower()
        
        # Check for "no violations" messages
        no_violations_phrases = [
            'no violations found', 'no tickets found', 'no records found',
            'no outstanding violations', 'no parking violations'
        ]
        
        if any(phrase in text_content for phrase in no_violations_phrases):
            return []  # Explicitly no violations
        
        # Look for violation data in tables
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 3:
                    row_data = [cell.get_text().strip() for cell in cells]
                    row_text = ' '.join(row_data).lower()
                    
                    # Check if this looks like violation data
                    if any(word in row_text for word in ['violation', 'ticket', 'fine', 'amount']):
                        violation = {
                            'violation_number': row_data[0] if len(row_data) > 0 else '',
                            'issue_date': row_data[1] if len(row_data) > 1 else '',
                            'violation_code': row_data[2] if len(row_data) > 2 else '',
                            'fine_amount': row_data[3] if len(row_data) > 3 else '',
                            'raw_data': row_data
                        }
                        violations.append(violation)
        
        return violations