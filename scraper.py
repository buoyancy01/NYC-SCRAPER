from playwright.async_api import async_playwright, Browser, Page, BrowserContext
import playwright_stealth
import logging
import asyncio
import random
import os
import aiofiles
from typing import Optional, Dict, List, Tuple
from urllib.parse import urljoin
import base64
from bs4 import BeautifulSoup
from captcha_client import TwoCaptchaClient
from models import ViolationDetail, ScrapingResult

logger = logging.getLogger(__name__)

class NYCServScraper:
    """Advanced NYC Serv violation scraper with anti-bot evasion"""
    
    def __init__(self, captcha_api_key: str):
        self.captcha_client = TwoCaptchaClient(captcha_api_key)
        self.base_url = "https://nycserv.nyc.gov/NYCServWeb/NYCSERVMain"
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        
        # Download directory for PDFs
        self.pdf_dir = "/app/backend/downloads/pdfs"
        os.makedirs(self.pdf_dir, exist_ok=True)
    
    async def __aenter__(self):
        """Async context manager entry"""
        await self._setup_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self._cleanup()
    
    async def _setup_browser(self):
        """Initialize browser with stealth configuration"""
        try:
            playwright = await async_playwright().start()
            
            # Launch browser with stealth settings
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-extensions',
                    '--disable-default-apps',
                    '--disable-web-security',
                    '--disable-features=TranslateUI',
                    '--disable-ipc-flooding-protection'
                ]
            )
            
            # Create context with realistic settings
            self.context = await self.browser.new_context(
                viewport={'width': 1366, 'height': 768},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Upgrade-Insecure-Requests': '1',
                    'Cache-Control': 'max-age=0',
                    'Connection': 'keep-alive'
                }
            )
            
            # Setup download behavior
            await self.context.set_extra_http_headers({
                'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
            })
            
            self.page = await self.context.new_page()
            
            # Apply stealth
            await playwright_stealth.stealth_async(self.page)
            
            # Set download path
            await self.page.set_extra_http_headers({
                'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            })
            
            logger.info("Browser setup completed with stealth configuration")
            
        except Exception as e:
            logger.error(f"Error setting up browser: {e}")
            await self._cleanup()
            raise
    
    async def _cleanup(self):
        """Clean up browser resources"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            logger.info("Browser cleanup completed")
        except Exception as e:
            logger.error(f"Error during browser cleanup: {e}")
    
    async def search_violations(self, license_plate: str, state: str) -> ScrapingResult:
        """
        Main method to search for parking violations
        """
        result = ScrapingResult(
            license_plate=license_plate,
            state=state,
            violations=[],
            success=False
        )
        
        try:
            logger.info(f"Starting violation search for {license_plate} ({state})")
            
            # Step 1: Navigate to the main page
            await self._navigate_to_main_page()
            
            # Step 2: Handle dropdown and navigate to violation search
            await self._navigate_to_violation_search()
            
            # Step 3: Fill in the search form
            await self._fill_search_form(license_plate, state)
            
            # Step 4: Handle CAPTCHA if present
            captcha_solved = await self._handle_captcha()
            result.captcha_solved = captcha_solved
            
            # Step 5: Submit search and get results
            violations = await self._extract_violations()
            result.violations = violations
            result.total_violations = len(violations)
            result.total_amount_due = sum(v.total_amount or 0 for v in violations)
            
            # Step 6: Download PDFs if available
            await self._download_violation_pdfs(violations)
            
            result.success = True
            logger.info(f"Successfully found {len(violations)} violations for {license_plate}")
            
        except Exception as e:
            error_msg = f"Error during scraping: {str(e)}"
            logger.error(error_msg)
            result.error_message = error_msg
            result.success = False
            
        return result
    
    async def _navigate_to_main_page(self):
        """Navigate to NYC Serv main page"""
        try:
            logger.info("Navigating to NYC Serv main page")
            await self.page.goto(self.base_url, wait_until='networkidle', timeout=30000)
            
            # Wait for page to be fully loaded
            await self.page.wait_for_timeout(random.randint(2000, 4000))
            
            # Check if we're on the right page
            title = await self.page.title()
            if "nyc" not in title.lower():
                raise Exception(f"Unexpected page title: {title}")
                
            logger.info("Successfully navigated to main page")
            
        except Exception as e:
            logger.error(f"Error navigating to main page: {e}")
            raise
    
    async def _navigate_to_violation_search(self):
        """Navigate to the violation search page"""
        try:
            logger.info("Navigating to violation search page")
            
            # Look for the dropdown or direct link to violation search
            # Try multiple selectors as the site might change
            selectors_to_try = [
                'select[name="ServiceName"]',
                'select#ServiceName',
                '.service-dropdown',
                'select[name="service"]',
                'select.form-control'
            ]
            
            dropdown_found = False
            for selector in selectors_to_try:
                try:
                    await self.page.wait_for_selector(selector, timeout=5000)
                    dropdown = self.page.locator(selector)
                    
                    # Select the parking violations option
                    await dropdown.select_option(label="Parking Violation")
                    await self.page.wait_for_timeout(1000)
                    
                    dropdown_found = True
                    logger.info(f"Found dropdown with selector: {selector}")
                    break
                    
                except Exception:
                    continue
            
            if not dropdown_found:
                # Try direct navigation to violation search page
                violation_url = urljoin(self.base_url, "PVO_Violation_Search")
                await self.page.goto(violation_url, wait_until='networkidle')
            
            # Wait for the violation search form to load
            await self.page.wait_for_timeout(random.randint(2000, 3000))
            
            logger.info("Successfully navigated to violation search page")
            
        except Exception as e:
            logger.error(f"Error navigating to violation search: {e}")
            raise
    
    async def _fill_search_form(self, license_plate: str, state: str):
        """Fill in the violation search form"""
        try:
            logger.info(f"Filling search form with plate: {license_plate}, state: {state}")
            
            # Wait for form elements to be visible
            await self.page.wait_for_timeout(2000)
            
            # Try different selectors for license plate field
            plate_selectors = [
                'input[name="LicensePlate"]',
                'input[name="licensePlate"]',
                'input[name="plate"]',
                'input#LicensePlate',
                'input#licensePlate'
            ]
            
            plate_filled = False
            for selector in plate_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.fill(selector, license_plate)
                    plate_filled = True
                    logger.info(f"Filled license plate with selector: {selector}")
                    break
                except Exception:
                    continue
            
            if not plate_filled:
                raise Exception("Could not find license plate input field")
            
            # Fill state field
            state_selectors = [
                'select[name="State"]',
                'select[name="state"]',
                'select#State',
                'select#state'
            ]
            
            state_filled = False
            for selector in state_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.select_option(selector, value=state)
                    state_filled = True
                    logger.info(f"Selected state with selector: {selector}")
                    break
                except Exception:
                    continue
            
            if not state_filled:
                raise Exception("Could not find state dropdown field")
            
            # Add human-like delay
            await self.page.wait_for_timeout(random.randint(1000, 2000))
            
            logger.info("Successfully filled search form")
            
        except Exception as e:
            logger.error(f"Error filling search form: {e}")
            raise
    
    async def _handle_captcha(self) -> bool:
        """Detect and solve CAPTCHA if present"""
        try:
            logger.info("Checking for CAPTCHA")
            
            # Wait a bit to let any CAPTCHA load
            await self.page.wait_for_timeout(2000)
            
            # Check for reCAPTCHA v2
            recaptcha_frame = None
            try:
                recaptcha_frame = self.page.frame_locator('iframe[src*="recaptcha"]').first
                if recaptcha_frame:
                    logger.info("Found reCAPTCHA v2")
                    return await self._solve_recaptcha_v2()
            except Exception:
                pass
            
            # Check for image CAPTCHA
            captcha_image = None
            image_selectors = [
                'img[src*="captcha"]',
                'img[alt*="captcha" i]',
                'img[id*="captcha" i]',
                '.captcha-image img',
                '#captcha_image'
            ]
            
            for selector in image_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=2000)
                    captcha_image = self.page.locator(selector).first
                    if captcha_image:
                        logger.info(f"Found image CAPTCHA with selector: {selector}")
                        return await self._solve_image_captcha(captcha_image)
                except Exception:
                    continue
            
            logger.info("No CAPTCHA detected")
            return True
            
        except Exception as e:
            logger.error(f"Error handling CAPTCHA: {e}")
            return False
    
    async def _solve_recaptcha_v2(self) -> bool:
        """Solve reCAPTCHA v2"""
        try:
            logger.info("Solving reCAPTCHA v2")
            
            # Get site key
            site_key = await self.page.evaluate('''() => {
                const script = document.querySelector('script[src*="recaptcha"]');
                return script ? script.getAttribute('data-sitekey') || 
                       document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey') : null;
            }''')
            
            if not site_key:
                logger.error("Could not find reCAPTCHA site key")
                return False
            
            page_url = self.page.url
            
            # Solve with 2captcha
            solution = await self.captcha_client.solve_recaptcha_v2(site_key, page_url)
            
            if solution:
                # Inject solution
                await self.page.evaluate(f'''() => {{
                    const textarea = document.querySelector('textarea[name="g-recaptcha-response"]');
                    if (textarea) {{
                        textarea.value = "{solution}";
                        textarea.style.display = 'block';
                    }}
                }}''')
                
                logger.info("reCAPTCHA v2 solved successfully")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error solving reCAPTCHA v2: {e}")
            return False
    
    async def _solve_image_captcha(self, captcha_image) -> bool:
        """Solve image CAPTCHA"""
        try:
            logger.info("Solving image CAPTCHA")
            
            # Screenshot the CAPTCHA image
            image_data = await captcha_image.screenshot()
            
            # Solve with 2captcha
            solution = await self.captcha_client.solve_image_captcha(image_data)
            
            if solution:
                # Find CAPTCHA input field and fill it
                input_selectors = [
                    'input[name*="captcha" i]',
                    'input[id*="captcha" i]',
                    'input[placeholder*="captcha" i]',
                    '.captcha-input input',
                    '#captcha_input'
                ]
                
                for selector in input_selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=2000)
                        await self.page.fill(selector, solution)
                        logger.info("Image CAPTCHA solved successfully")
                        return True
                    except Exception:
                        continue
                
                logger.error("Could not find CAPTCHA input field")
                return False
            
            return False
            
        except Exception as e:
            logger.error(f"Error solving image CAPTCHA: {e}")
            return False
    
    async def _extract_violations(self) -> List[ViolationDetail]:
        """Extract violation details from results page"""
        try:
            logger.info("Submitting search and extracting violations")
            
            # Submit the search form
            submit_selectors = [
                'input[type="submit"]',
                'button[type="submit"]',
                'input[value*="Search" i]',
                'button:has-text("Search")',
                '#search_button',
                '.search-button'
            ]
            
            form_submitted = False
            for selector in submit_selectors:
                try:
                    await self.page.wait_for_selector(selector, timeout=3000)
                    await self.page.click(selector)
                    form_submitted = True
                    logger.info(f"Submitted form with selector: {selector}")
                    break
                except Exception:
                    continue
            
            if not form_submitted:
                raise Exception("Could not find or click submit button")
            
            # Wait for results to load
            await self.page.wait_for_timeout(5000)
            
            # Check for "no violations found" message
            no_results_selectors = [
                ':text("no violations")',
                ':text("No violations")',
                ':text("not found")',
                ':text("No records")',
                '.no-results',
                '.no-violations'
            ]
            
            for selector in no_results_selectors:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=2000)
                    if element:
                        logger.info("No violations found for this license plate")
                        return []
                except Exception:
                    continue
            
            # Extract violation details from the results table/list
            violations = []
            
            # Try to find violation data in various formats
            page_content = await self.page.content()
            soup = BeautifulSoup(page_content, 'html.parser')
            
            # Look for table rows with violation data
            violation_rows = []
            
            # Try different table structures
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows[1:]:  # Skip header row
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 3:  # Minimum columns for violation data
                        violation_rows.append(cells)
            
            # Extract violation details from each row
            for cells in violation_rows:
                try:
                    violation = self._parse_violation_row(cells)
                    if violation:
                        violations.append(violation)
                except Exception as e:
                    logger.error(f"Error parsing violation row: {e}")
                    continue
            
            logger.info(f"Extracted {len(violations)} violations")
            return violations
            
        except Exception as e:
            logger.error(f"Error extracting violations: {e}")
            return []
    
    def _parse_violation_row(self, cells) -> Optional[ViolationDetail]:
        """Parse individual violation row"""
        try:
            if len(cells) < 3:
                return None
            
            # Extract text from cells
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            
            violation = ViolationDetail()
            
            # Map common field patterns
            for i, text in enumerate(cell_texts):
                if not text:
                    continue
                
                # Ticket number (usually first column or contains digits)
                if i == 0 or (text.isdigit() and len(text) >= 8):
                    violation.ticket_number = text
                
                # Look for date patterns
                elif any(month in text for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                                    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
                    violation.violation_date = text
                
                # Look for dollar amounts
                elif '$' in text:
                    amount = self._extract_amount(text)
                    if amount:
                        if 'fine' in text.lower():
                            violation.fine_amount = amount
                        elif 'penalty' in text.lower():
                            violation.penalty_amount = amount
                        else:
                            violation.total_amount = amount
                
                # Violation description (longer text fields)
                elif len(text) > 10 and not text.replace('.', '').isdigit():
                    violation.violation_description = text
            
            # Set total amount if not explicitly found
            if not violation.total_amount:
                total = (violation.fine_amount or 0) + (violation.penalty_amount or 0)
                if total > 0:
                    violation.total_amount = total
            
            return violation if violation.ticket_number else None
            
        except Exception as e:
            logger.error(f"Error parsing violation row: {e}")
            return None
    
    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract dollar amount from text"""
        try:
            import re
            # Remove currency symbols and extract number
            amount_match = re.search(r'[\$]?(\d+\.?\d*)', text.replace(',', ''))
            if amount_match:
                return float(amount_match.group(1))
            return None
        except Exception:
            return None
    
    async def _download_violation_pdfs(self, violations: List[ViolationDetail]):
        """Download PDF tickets for violations"""
        try:
            logger.info(f"Attempting to download PDFs for {len(violations)} violations")
            
            for violation in violations:
                if not violation.ticket_number:
                    continue
                
                try:
                    # Look for PDF download links
                    pdf_selectors = [
                        f'a[href*="{violation.ticket_number}"]',
                        'a[href*="pdf"]',
                        'a:has-text("PDF")',
                        'a:has-text("Download")',
                        '.pdf-link',
                        '.download-link'
                    ]
                    
                    for selector in pdf_selectors:
                        try:
                            pdf_link = await self.page.wait_for_selector(selector, timeout=2000)
                            if pdf_link:
                                href = await pdf_link.get_attribute('href')
                                if href and 'pdf' in href.lower():
                                    pdf_path = await self._download_pdf(href, violation.ticket_number)
                                    if pdf_path:
                                        violation.pdf_downloaded = True
                                        violation.pdf_path = pdf_path
                                        violation.pdf_url = href
                                    break
                        except Exception:
                            continue
                            
                except Exception as e:
                    logger.error(f"Error downloading PDF for ticket {violation.ticket_number}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error in PDF download process: {e}")
    
    async def _download_pdf(self, pdf_url: str, ticket_number: str) -> Optional[str]:
        """Download individual PDF file"""
        try:
            # Make URL absolute if needed
            if pdf_url.startswith('/'):
                pdf_url = urljoin(self.base_url, pdf_url)
            
            # Download PDF using Playwright
            async with self.page.expect_download() as download_info:
                await self.page.goto(pdf_url)
            
            download = await download_info.value
            
            # Save to our PDF directory
            pdf_filename = f"ticket_{ticket_number}.pdf"
            pdf_path = os.path.join(self.pdf_dir, pdf_filename)
            
            await download.save_as(pdf_path)
            
            logger.info(f"Downloaded PDF: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            logger.error(f"Error downloading PDF from {pdf_url}: {e}")
            return None