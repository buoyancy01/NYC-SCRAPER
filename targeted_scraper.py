"""
Targeted NYC Violations Web Scraper
Focuses on getting data that's NOT available in the public API:
- Exact violation locations
- Hearing status and dates  
- Officer badge numbers
- Current balance due
- Ticket PDF images
- Enhanced payment details
"""

import asyncio
import os
import re
import json
import aiohttp
# import aiofiles  # Using regular file I/O instead
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class NYCWebScraper:
    """Targeted web scraper for data not available in NYC Open Data API"""
    
    def __init__(self, captcha_api_key: Optional[str] = None, proxy_list: List[str] = None):
        self.base_url = "https://nycserv.nyc.gov/NYCServWeb/PVO_Search.jsp"
        self.captcha_api_key = captcha_api_key
        self.proxies = proxy_list or []
        self.current_proxy_index = 0
        
    async def get_enhanced_violation_data(self, license_plate: str, state: str = "NY") -> Dict:
        """
        Get comprehensive violation data by combining API data with web scraping
        """
        start_time = datetime.now()
        
        logger.info(f"🔍 Getting enhanced data for {license_plate} ({state})")
        
        result = {
            'license_plate': license_plate.upper(),
            'state': state.upper(),
            'violations': [],
            'success': False,
            'error': None,
            'data_sources': [],
            'processing_time': 0,
            'downloaded_pdfs': [],
            'scraped_details': []
        }
        
        try:
            # Step 1: Get base data from API (fast and reliable)
            logger.info("📡 Getting base data from NYC Open Data API...")
            api_data = await self._get_api_data(license_plate, state)
            
            if api_data['success']:
                result['violations'] = api_data['violations']
                result['data_sources'].append('NYC_API')
                logger.info(f"✅ API returned {len(api_data['violations'])} violations")
                
                # Step 2: Enhance with web scraping for missing details
                if result['violations']:
                    logger.info("🌐 Enhancing with web scraping...")
                    enhanced_data = await self._scrape_additional_details(
                        license_plate, state, result['violations']
                    )
                    
                    # Merge scraped data back into violations
                    result['violations'] = enhanced_data['enhanced_violations']
                    result['scraped_details'] = enhanced_data['scraped_details']
                    result['downloaded_pdfs'] = enhanced_data['downloaded_pdfs']
                    result['data_sources'].append('WEB_SCRAPING')
                
                result['success'] = True
            else:
                logger.warning("⚠️ API failed, trying pure web scraping...")
                # Fallback to pure web scraping
                web_result = await self._scrape_violations_only(license_plate, state)
                result.update(web_result)
                result['data_sources'].append('WEB_ONLY')
                
        except Exception as e:
            logger.error(f"❌ Enhanced scraping failed: {e}")
            result['error'] = str(e)
        
        finally:
            result['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        return result
    
    async def _get_api_data(self, license_plate: str, state: str) -> Dict:
        """Get base violation data from NYC API"""
        try:
            from nyc_api_client import NYCViolationsAPI
            api_client = NYCViolationsAPI()
            return await api_client.search_violations(license_plate, state)
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return {'success': False, 'error': str(e), 'violations': []}
    
    async def _scrape_additional_details(self, license_plate: str, state: str, violations: List[Dict]) -> Dict:
        """Scrape additional details not available in API"""
        
        result = {
            'enhanced_violations': violations.copy(),
            'scraped_details': [],
            'downloaded_pdfs': []
        }
        
        async with async_playwright() as p:
            browser = await self._launch_browser(p)
            page = await browser.new_page()
            
            try:
                # Navigate to NYC violations site
                await self._setup_page(page)
                await page.goto(self.base_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                
                # Fill search form
                await self._fill_search_form(page, license_plate, state)
                
                # Handle CAPTCHA if present
                await self._handle_captcha(page)
                
                # Submit search
                await self._submit_search(page)
                
                # Wait for results
                await page.wait_for_timeout(5000)
                
                # Parse results page to find violation rows
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                # Find violation table rows
                violation_rows = self._find_violation_rows(soup)
                logger.info(f"📊 Found {len(violation_rows)} violation rows on page")
                
                # Process each violation to get additional details
                for i, violation in enumerate(result['enhanced_violations']):
                    try:
                        # Find matching row on the web page
                        matching_row = self._find_matching_row(violation, violation_rows)
                        
                        if matching_row:
                            logger.info(f"🔍 Getting details for violation {violation.get('summons_number')}")
                            
                            # Get additional details
                            additional_details = await self._get_violation_details(
                                page, matching_row, violation
                            )
                            
                            # Merge additional details into violation
                            violation.update(additional_details)
                            
                            # Download PDF if available
                            pdf_result = await self._download_violation_pdf(violation)
                            if pdf_result:
                                result['downloaded_pdfs'].append(pdf_result)
                                violation['local_pdf_path'] = pdf_result.get('local_path')
                            
                            result['scraped_details'].append({
                                'summons_number': violation.get('summons_number'),
                                'additional_fields_found': len(additional_details),
                                'details': additional_details
                            })
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Could not enhance violation {i+1}: {e}")
                        
            except Exception as e:
                logger.error(f"❌ Web scraping failed: {e}")
                
            finally:
                await browser.close()
        
        return result
    
    async def _launch_browser(self, playwright):
        """Launch browser with proxy support"""
        proxy = self._get_next_proxy()
        
        launch_options = {
            'headless': True,
            'args': [
                '--no-sandbox',
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=VizDisplayCompositor'
            ]
        }
        
        if proxy:
            logger.info(f"🌐 Using proxy: {proxy}")
            launch_options['proxy'] = {'server': proxy}
        
        return await playwright.chromium.launch(**launch_options)
    
    def _get_next_proxy(self) -> Optional[str]:
        """Get next proxy from rotation"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    async def _setup_page(self, page):
        """Setup page with realistic headers and settings"""
        await page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none'
        })
        
        # Set viewport
        await page.set_viewport_size({'width': 1920, 'height': 1080})
    
    async def _fill_search_form(self, page, license_plate: str, state: str):
        """Fill the license plate search form"""
        logger.info(f"📝 Filling search form: {license_plate} ({state})")
        
        # Wait for form to be ready
        await page.wait_for_selector('input[name=\"plateNumber\"]', timeout=10000)
        
        # Fill license plate
        await page.fill('input[name=\"plateNumber\"]', license_plate)
        
        # Set state if not NY
        if state.upper() != "NY":
            try:
                await page.select_option('select[name=\"state\"]', value=state.upper())
                logger.info(f"✅ Set state to {state}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set state: {e}")
    
    async def _handle_captcha(self, page):
        """Handle CAPTCHA if present"""
        # Check for CAPTCHA
        captcha_element = await page.query_selector('.g-recaptcha')
        if not captcha_element:
            logger.info("✅ No CAPTCHA detected")
            return
        
        logger.warning("🤖 CAPTCHA detected")
        
        if not self.captcha_api_key:
            raise Exception("CAPTCHA detected but no API key provided. Set TWOCAPTCHA_API_KEY environment variable.")
        
        # Get site key
        site_key_element = await page.query_selector('[data-sitekey]')
        if not site_key_element:
            raise Exception("CAPTCHA found but no site key")
        
        site_key = await site_key_element.get_attribute('data-sitekey')
        
        # Solve CAPTCHA using 2captcha
        solution = await self._solve_captcha(site_key)
        
        # Inject solution
        await page.evaluate(f'''
            () => {{
                const responseField = document.getElementById("g-recaptcha-response");
                if (responseField) {{
                    responseField.innerHTML = "{solution}";
                    responseField.value = "{solution}";
                    responseField.style.display = "block";
                }}
            }}
        ''')
        
        logger.info("✅ CAPTCHA solution injected")
    
    async def _solve_captcha(self, site_key: str) -> str:
        """Solve CAPTCHA using 2captcha service"""
        async with aiohttp.ClientSession() as session:
            # Submit CAPTCHA
            submit_data = {
                'key': self.captcha_api_key,
                'method': 'userrecaptcha',
                'googlekey': site_key,
                'pageurl': self.base_url,
                'json': 1
            }
            
            async with session.post('http://2captcha.com/in.php', data=submit_data) as response:
                result = await response.json()
                
                if result.get('status') != 1:
                    raise Exception(f"CAPTCHA submit failed: {result.get('error_text')}")
                
                captcha_id = result['request']
            
            # Poll for solution
            for attempt in range(60):
                await asyncio.sleep(5)
                
                params = {
                    'key': self.captcha_api_key,
                    'action': 'get',
                    'id': captcha_id,
                    'json': 1
                }
                
                async with session.get('http://2captcha.com/res.php', params=params) as response:
                    result = await response.json()
                    
                    if result.get('status') == 1:
                        return result['request']
                    elif result.get('error_text') != 'CAPCHA_NOT_READY':
                        raise Exception(f"CAPTCHA error: {result.get('error_text')}")
            
            raise Exception("CAPTCHA timeout")
    
    async def _submit_search(self, page):
        """Submit the search form"""
        logger.info("🔍 Submitting search...")
        
        # Find and click the correct search button (usually the second one for plate search)
        search_buttons = await page.query_selector_all('input[type=\"submit\"][value=\"SEARCH\"]')
        
        if len(search_buttons) >= 2:
            await search_buttons[1].click()  # Plate search button
            logger.info("✅ Clicked plate search button")
        elif len(search_buttons) == 1:
            await search_buttons[0].click()
            logger.info("✅ Clicked search button")
        else:
            raise Exception("Could not find search button")
    
    def _find_violation_rows(self, soup: BeautifulSoup) -> List[Dict]:
        """Find violation rows in the results table"""
        violation_rows = []
        
        # Look for tables containing violation data
        tables = soup.find_all('table')
        
        for table_idx, table in enumerate(tables):
            rows = table.find_all('tr')
            
            for row_idx, row in enumerate(rows):
                cells = row.find_all(['td', 'th'])
                
                if len(cells) >= 3:  # Need at least 3 columns
                    cell_texts = [cell.get_text().strip() for cell in cells]
                    row_text = ' '.join(cell_texts).lower()
                    
                    # Check if this looks like a violation row
                    if any(keyword in row_text for keyword in ['violation', 'ticket', 'summons', '$']):
                        # Look for buttons
                        details_button = row.find('input', {'value': re.compile('details', re.I)})
                        image_button = row.find('input', {'value': re.compile('image', re.I)})
                        
                        violation_rows.append({
                            'table_index': table_idx,
                            'row_index': row_idx,
                            'cells': cell_texts,
                            'has_details_button': details_button is not None,
                            'has_image_button': image_button is not None,
                            'row_html': str(row)
                        })
        
        return violation_rows
    
    def _find_matching_row(self, violation: Dict, violation_rows: List[Dict]) -> Optional[Dict]:
        """Find web page row that matches API violation data"""
        summons_number = violation.get('summons_number', '')
        issue_date = violation.get('issue_date', '')
        
        for row in violation_rows:
            row_text = ' '.join(row['cells'])
            
            # Try to match by summons number (most reliable)
            if summons_number and summons_number in row_text:
                logger.info(f"✅ Matched by summons number: {summons_number}")
                return row
            
            # Try to match by date if no summons match
            if issue_date:
                # Try different date formats
                date_formats = [
                    issue_date,  # Original format from API
                    issue_date.replace('-', '/'),  # Convert to slash format
                    issue_date.replace('/', '-'),  # Convert to dash format
                ]
                
                for date_format in date_formats:
                    if date_format in row_text:
                        logger.info(f"✅ Matched by date: {date_format}")
                        return row
        
        logger.warning(f"⚠️ Could not find matching row for {summons_number}")
        return None
    
    async def _get_violation_details(self, page, matching_row: Dict, violation: Dict) -> Dict:
        """Extract additional violation details from the web page"""
        additional_details = {}
        
        try:
            # Extract details from the row itself
            cells = matching_row['cells']
            
            # Try to extract location information (usually in one of the cells)
            for cell in cells:
                if any(indicator in cell.lower() for indicator in ['st ', 'ave ', 'blvd ', 'rd ', 'pkwy ']):
                    additional_details['violation_location'] = cell
                    break
            
            # Look for officer information
            for cell in cells:
                if re.search(r'\\b\\d{4,6}\\b', cell):  # Badge number pattern
                    additional_details['officer_badge'] = cell
                    break
            
            # If this row has a details button, we could click it for more info
            # (This would require more complex implementation based on the actual site structure)
            if matching_row.get('has_details_button'):
                # Placeholder for clicking details button and extracting popup data
                additional_details['details_available'] = True
                additional_details['hearing_status'] = 'DETAILS_AVAILABLE_BUT_NOT_EXTRACTED'
            
            # Extract any additional fields from the row
            if len(cells) > 5:  # More columns might contain additional info
                for i, cell in enumerate(cells[5:], 5):
                    if cell and cell.strip():
                        additional_details[f'additional_field_{i}'] = cell
            
        except Exception as e:
            logger.warning(f"⚠️ Error extracting details: {e}")
        
        return additional_details
    
    async def _download_violation_pdf(self, violation: Dict) -> Optional[Dict]:
        """Download the PDF image for a violation"""
        summons_image = violation.get('summons_image', {})
        pdf_url = summons_image.get('url')
        
        if not pdf_url:
            return None
        
        try:
            summons_number = violation.get('summons_number', 'unknown')
            
            # Create downloads directory
            downloads_dir = '/home/scrapybara/NYC-SCRAPER-main/downloads'
            os.makedirs(downloads_dir, exist_ok=True)
            
            # Generate filename
            filename = f"ticket_{summons_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            file_path = os.path.join(downloads_dir, filename)
            
            # Download PDF
            async with aiohttp.ClientSession() as session:
                async with session.get(pdf_url) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        with open(file_path, 'wb') as f:
                            f.write(content)
                        
                        logger.info(f"✅ Downloaded PDF: {filename}")
                        
                        return {
                            'summons_number': summons_number,
                            'local_path': file_path,
                            'original_url': pdf_url,
                            'file_size': len(content),
                            'download_success': True
                        }
            
        except Exception as e:
            logger.error(f"❌ PDF download failed for {summons_number}: {e}")
            return {
                'summons_number': summons_number,
                'error': str(e),
                'download_success': False
            }
        
        return None
    
    async def _scrape_violations_only(self, license_plate: str, state: str) -> Dict:
        """Pure web scraping fallback when API is unavailable"""
        # This would implement pure web scraping as fallback
        # For now, return error indicating API is required
        return {
            'success': False,
            'error': 'Pure web scraping fallback not implemented. API connection required.',
            'violations': []
        }


# Test function
async def test_targeted_scraper():
    """Test the targeted web scraper"""
    
    # Get configuration from environment
    captcha_api_key = os.getenv('TWOCAPTCHA_API_KEY')
    proxy_list = []
    
    if os.getenv('PROXY_LIST'):
        proxy_list = [p.strip() for p in os.getenv('PROXY_LIST').split(',') if p.strip()]
    
    print("🧪 TESTING TARGETED NYC WEB SCRAPER")
    print("="*60)
    print(f"CAPTCHA API Key: {'✅ Configured' if captcha_api_key else '❌ Not configured'}")
    print(f"Proxies: {'✅ ' + str(len(proxy_list)) + ' configured' if proxy_list else '❌ Not configured'}")
    print()
    
    # Initialize scraper
    scraper = NYCWebScraper(
        captcha_api_key=captcha_api_key,
        proxy_list=proxy_list
    )
    
    # Test with a plate that has violations
    test_plate = "AW716M"
    test_state = "NJ"
    
    print(f"🔍 Testing with {test_plate} ({test_state})")
    print()
    
    result = await scraper.get_enhanced_violation_data(test_plate, test_state)
    
    # Display results
    print("📊 RESULTS:")
    print(f"   Success: {result['success']}")
    print(f"   Processing Time: {result['processing_time']:.2f}s")
    print(f"   Total Violations: {len(result['violations'])}")
    print(f"   Data Sources: {', '.join(result['data_sources'])}")
    print(f"   Downloaded PDFs: {len(result['downloaded_pdfs'])}")
    print(f"   Scraped Details: {len(result['scraped_details'])}")
    
    if result['success'] and result['violations']:
        print()
        print("🎫 ENHANCED VIOLATION SAMPLE:")
        violation = result['violations'][0]
        
        # Show API fields
        print("   📡 From API:")
        api_fields = ['summons_number', 'issue_date', 'violation_code', 'fine_amount', 'amount_due', 'status']
        for field in api_fields:
            print(f"      {field}: {violation.get(field)}")
        
        # Show scraped fields
        print("   🌐 From Web Scraping:")
        scraped_fields = [k for k in violation.keys() if k not in api_fields and not k.startswith('raw_')]
        for field in scraped_fields:
            print(f"      {field}: {violation.get(field)}")
    
    if result.get('downloaded_pdfs'):
        print()
        print("📄 DOWNLOADED PDFs:")
        for pdf in result['downloaded_pdfs']:
            print(f"   {pdf}")
    
    if result.get('error'):
        print(f"\\n❌ Error: {result['error']}")
    
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(test_targeted_scraper())