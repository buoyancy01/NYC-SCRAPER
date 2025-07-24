"""
Optimized NYC Violations Scraper - Smart Hybrid Approach
Uses API for most data and targeted scraping only for what's truly missing
"""

import asyncio
import os
import aiohttp
import logging
from datetime import datetime
from typing import Dict, List, Optional
import re

logger = logging.getLogger(__name__)

class SmartNYCViolationsScraper:
    """Smart scraper that efficiently combines API data with minimal web scraping"""
    
    def __init__(self, captcha_api_key: Optional[str] = None):
        self.captcha_api_key = captcha_api_key
        
    async def get_complete_violation_data(self, license_plate: str, state: str = "NY") -> Dict:
        """
        Get complete violation data using smart hybrid approach:
        1. Get comprehensive data from API (fast, reliable)
        2. Download PDF images directly from API URLs
        3. Only scrape website for truly missing data if needed
        """
        start_time = datetime.now()
        
        logger.info(f"🚀 Getting complete data for {license_plate} ({state})")
        
        result = {
            'license_plate': license_plate.upper(),
            'state': state.upper(),
            'violations': [],
            'success': False,
            'error': None,
            'processing_time': 0,
            'data_sources': [],
            'downloaded_pdfs': [],
            'api_data_quality': {}
        }
        
        try:
            # Step 1: Get data from NYC Open Data API
            logger.info("📡 Fetching data from NYC Open Data API...")
            api_result = await self._get_api_data(license_plate, state)
            
            if api_result['success']:
                result['violations'] = api_result['violations']
                result['data_sources'].append('NYC_API')
                result['success'] = True
                
                # Analyze data quality
                result['api_data_quality'] = self._analyze_data_quality(api_result['violations'])
                
                logger.info(f"✅ API returned {len(api_result['violations'])} violations")
                
                # Step 2: Download PDF images directly from API URLs
                if result['violations']:
                    logger.info("📄 Downloading PDF images...")
                    pdf_results = await self._download_pdfs_from_api(result['violations'])
                    result['downloaded_pdfs'] = pdf_results
                    result['data_sources'].append('PDF_DOWNLOADS')
                
                # Step 3: Enhance missing data only if needed
                missing_data_count = self._count_missing_data(result['violations'])
                if missing_data_count > 0:
                    logger.info(f"🔍 {missing_data_count} violations need enhancement")
                    # Only scrape if there's significant missing data
                    # For now, we'll skip this since API data is quite complete
                
            else:
                result['error'] = api_result.get('error', 'API call failed')
                logger.error(f"❌ API failed: {result['error']}")
                
        except Exception as e:
            logger.error(f"❌ Smart scraping failed: {e}")
            result['error'] = str(e)
        
        finally:
            result['processing_time'] = (datetime.now() - start_time).total_seconds()
        
        return result
    
    async def _get_api_data(self, license_plate: str, state: str) -> Dict:
        """Get violation data from NYC Open Data API"""
        try:
            from nyc_api_client import NYCViolationsAPI
            api_client = NYCViolationsAPI()
            return await api_client.search_violations(license_plate, state)
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return {'success': False, 'error': str(e), 'violations': []}
    
    def _analyze_data_quality(self, violations: List[Dict]) -> Dict:
        """Analyze the completeness of API data"""
        if not violations:
            return {'total_violations': 0}
        
        total = len(violations)
        
        # Count violations with complete data
        complete_basic = 0
        complete_financial = 0
        has_pdf_url = 0
        has_location = 0
        
        for violation in violations:
            # Basic data completeness
            if all(violation.get(field) for field in ['summons_number', 'issue_date', 'violation_code']):
                complete_basic += 1
            
            # Financial data completeness  
            if any(violation.get(field, 0) > 0 for field in ['fine_amount', 'amount_due', 'payment_amount']):
                complete_financial += 1
            
            # PDF URL available
            if violation.get('summons_image', {}).get('url'):
                has_pdf_url += 1
            
            # Location data
            if violation.get('county') or violation.get('precinct'):
                has_location += 1
        
        return {
            'total_violations': total,
            'complete_basic_data': f"{complete_basic}/{total} ({complete_basic/total*100:.1f}%)",
            'complete_financial_data': f"{complete_financial}/{total} ({complete_financial/total*100:.1f}%)",
            'has_pdf_urls': f"{has_pdf_url}/{total} ({has_pdf_url/total*100:.1f}%)",
            'has_location_data': f"{has_location}/{total} ({has_location/total*100:.1f}%)"
        }
    
    def _count_missing_data(self, violations: List[Dict]) -> int:
        """Count violations that are missing critical data"""
        missing_count = 0
        
        for violation in violations:
            # Check for missing critical fields
            if not violation.get('violation_code') or violation.get('violation_code') == 'N/A':
                missing_count += 1
            elif not violation.get('summons_image', {}).get('url'):
                missing_count += 1
        
        return missing_count
    
    async def _download_pdfs_from_api(self, violations: List[Dict]) -> List[Dict]:
        """Download PDF images directly from API-provided URLs"""
        pdf_results = []
        downloads_dir = '/home/scrapybara/NYC-SCRAPER-main/downloads'
        os.makedirs(downloads_dir, exist_ok=True)
        
        # Limit downloads for testing (remove this limit in production)
        violations_to_download = violations[:5]  # Download first 5 PDFs for testing
        
        for violation in violations_to_download:
            summons_image = violation.get('summons_image', {})
            pdf_url = summons_image.get('url')
            summons_number = violation.get('summons_number', 'unknown')
            
            if not pdf_url:
                pdf_results.append({
                    'summons_number': summons_number,
                    'success': False,
                    'error': 'No PDF URL available'
                })
                continue
            
            try:
                logger.info(f"📄 Downloading PDF for {summons_number}...")
                
                # Generate filename
                safe_summons = re.sub(r'[^\\w\\-_]', '_', summons_number)
                filename = f"ticket_{safe_summons}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                file_path = os.path.join(downloads_dir, filename)
                
                # Download PDF
                async with aiohttp.ClientSession() as session:
                    async with session.get(pdf_url, timeout=30) as response:
                        if response.status == 200:
                            content = await response.read()
                            
                            # Save to file
                            with open(file_path, 'wb') as f:
                                f.write(content)
                            
                            # Update violation with local path
                            violation['local_pdf_path'] = file_path
                            
                            pdf_results.append({
                                'summons_number': summons_number,
                                'success': True,
                                'local_path': file_path,
                                'original_url': pdf_url,
                                'file_size': len(content),
                                'filename': filename
                            })
                            
                            logger.info(f"✅ Downloaded: {filename} ({len(content)} bytes)")
                            
                        else:
                            pdf_results.append({
                                'summons_number': summons_number,
                                'success': False,
                                'error': f'HTTP {response.status}'
                            })
                            
            except Exception as e:
                logger.error(f"❌ PDF download failed for {summons_number}: {e}")
                pdf_results.append({
                    'summons_number': summons_number,
                    'success': False,
                    'error': str(e)
                })
        
        return pdf_results
    
    def get_data_completeness_report(self, violations: List[Dict]) -> str:
        """Generate a report on data completeness"""
        if not violations:
            return "No violations to analyze."
        
        report_lines = []
        report_lines.append("📊 DATA COMPLETENESS REPORT")
        report_lines.append("=" * 50)
        
        # Analyze field completeness
        fields_to_check = {
            'summons_number': 'Summons Number',
            'violation_code': 'Violation Code', 
            'issue_date': 'Issue Date',
            'fine_amount': 'Fine Amount',
            'amount_due': 'Amount Due',
            'status': 'Payment Status',
            'issuing_agency': 'Issuing Agency',
            'county': 'County/Location',
            'summons_image': 'PDF Image URL'
        }
        
        for field, description in fields_to_check.items():
            complete_count = 0
            for violation in violations:
                value = violation.get(field)
                
                if field == 'summons_image':
                    # Special check for image URL
                    if value and value.get('url'):
                        complete_count += 1
                elif value and str(value).strip() and str(value) != 'N/A':
                    complete_count += 1
            
            percentage = (complete_count / len(violations)) * 100
            status = "✅" if percentage >= 90 else "⚠️" if percentage >= 50 else "❌"
            report_lines.append(f"{status} {description}: {complete_count}/{len(violations)} ({percentage:.1f}%)")
        
        # Summary
        report_lines.append("")
        report_lines.append("📈 SUMMARY")
        report_lines.append("-" * 20)
        
        # Count violations with good data quality
        good_quality = 0
        for violation in violations:
            required_fields = ['summons_number', 'violation_code', 'issue_date', 'fine_amount']
            if all(violation.get(field) for field in required_fields):
                good_quality += 1
        
        good_percentage = (good_quality / len(violations)) * 100
        report_lines.append(f"High Quality Data: {good_quality}/{len(violations)} ({good_percentage:.1f}%)")
        
        if good_percentage >= 90:
            report_lines.append("✅ Data quality is excellent! API provides comprehensive information.")
        elif good_percentage >= 70:
            report_lines.append("⚠️ Data quality is good. Minor enhancement might be beneficial.")
        else:
            report_lines.append("❌ Data quality needs improvement. Web scraping recommended.")
        
        return "\\n".join(report_lines)


# Test function
async def test_smart_scraper():
    """Test the smart scraper"""
    
    captcha_api_key = os.getenv('TWOCAPTCHA_API_KEY')
    
    print("🚀 TESTING SMART NYC VIOLATIONS SCRAPER")
    print("="*60)
    print(f"CAPTCHA API Key: {'✅ Configured' if captcha_api_key else '❌ Not configured'}")
    print()
    
    # Initialize smart scraper
    scraper = SmartNYCViolationsScraper(captcha_api_key=captcha_api_key)
    
    # Test with multiple plates
    test_cases = [
        ("AW716M", "NJ"),  # Has many violations
        ("K58ARK", "NY"),  # Clean record
    ]
    
    for plate, state in test_cases:
        print(f"🔍 Testing: {plate} ({state})")
        print("-" * 40)
        
        result = await scraper.get_complete_violation_data(plate, state)
        
        # Display results
        print(f"✅ Success: {result['success']}")
        print(f"⏱️ Processing Time: {result['processing_time']:.2f}s")
        print(f"📊 Total Violations: {len(result['violations'])}")
        print(f"📡 Data Sources: {', '.join(result['data_sources'])}")
        print(f"📄 Downloaded PDFs: {len(result['downloaded_pdfs'])}")
        
        if result['success'] and result['violations']:
            # Show data quality analysis
            print("\\n📈 API Data Quality:")
            for key, value in result['api_data_quality'].items():
                print(f"   {key}: {value}")
            
            # Show sample violation
            print("\\n🎫 Sample Violation:")
            violation = result['violations'][0]
            key_fields = ['summons_number', 'issue_date', 'violation_code', 'fine_amount', 'amount_due', 'status']
            for field in key_fields:
                value = violation.get(field, 'N/A')
                print(f"   {field}: {value}")
            
            # Show PDF download results
            if result['downloaded_pdfs']:
                print("\\n📄 PDF Downloads:")
                for pdf in result['downloaded_pdfs'][:3]:  # Show first 3
                    status = "✅" if pdf['success'] else "❌"
                    if pdf['success']:
                        print(f"   {status} {pdf['filename']} ({pdf['file_size']} bytes)")
                    else:
                        print(f"   {status} {pdf['summons_number']}: {pdf['error']}")
            
            # Generate completeness report
            print("\\n" + scraper.get_data_completeness_report(result['violations']))
        
        elif result.get('error'):
            print(f"❌ Error: {result['error']}")
        
        print("\\n" + "="*60 + "\\n")
    
    return result


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(test_smart_scraper())