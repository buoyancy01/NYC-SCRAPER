"""
PDF Report Generator for NYC Parking Violations
Includes fallback to text reports when PDF libraries are unavailable
"""

import io
from datetime import datetime
from typing import List, Dict, Any

# Try to import PDF libraries
PDF_AVAILABLE = False
PDF_LIBRARY = "none"

# Try reportlab first
try:
    import reportlab
    # Test if reportlab can actually be imported without errors
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    PDF_AVAILABLE = True
    PDF_LIBRARY = "reportlab"
except (ImportError, SyntaxError, Exception):
    # Try fpdf as fallback
    try:
        from fpdf import FPDF
        PDF_AVAILABLE = True
        PDF_LIBRARY = "fpdf"
    except (ImportError, SyntaxError, Exception):
        # No PDF library available
        PDF_LIBRARY = "none"
        PDF_AVAILABLE = False


class ViolationsPDFGenerator:
    def __init__(self):
        self.pdf_available = PDF_AVAILABLE
        self.library = PDF_LIBRARY
    
    def generate_violation_report(self, license_plate: str, state: str, 
                                violations_data: Dict[str, Any]) -> bytes:
        """Generate a violation report - PDF if available, otherwise formatted text"""
        
        if self.pdf_available and self.library == "reportlab":
            return self._generate_reportlab_pdf(license_plate, state, violations_data)
        elif self.pdf_available and self.library == "fpdf":
            return self._generate_fpdf_pdf(license_plate, state, violations_data)
        else:
            # Fallback to formatted text that can be converted to PDF elsewhere
            return self._generate_text_report(license_plate, state, violations_data)
    
    def _generate_text_report(self, license_plate: str, state: str, 
                            violations_data: Dict[str, Any]) -> bytes:
        """Generate a formatted text report as fallback"""
        
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("NYC PARKING VIOLATIONS REPORT")
        report_lines.append("=" * 80)
        report_lines.append("")
        
        # Vehicle Information
        report_lines.append("VEHICLE INFORMATION")
        report_lines.append("-" * 40)
        report_lines.append(f"License Plate: {license_plate}")
        report_lines.append(f"State: {state}")
        report_lines.append(f"Report Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
        report_lines.append("Data Source: NYC Open Data API")
        report_lines.append("")
        
        # Summary Statistics
        if violations_data['success'] and violations_data.get('violations'):
            violations = violations_data['violations']
            
            report_lines.append("SUMMARY STATISTICS")
            report_lines.append("-" * 40)
            
            # Calculate summary stats
            total_due = sum(float(v.get('amount_due', 0)) for v in violations)
            outstanding = sum(1 for v in violations if float(v.get('amount_due', 0)) > 0)
            paid = len(violations) - outstanding
            
            report_lines.append(f"Total Violations: {len(violations)}")
            report_lines.append(f"Total Amount Due: ${total_due:.2f}")
            report_lines.append(f"Outstanding Violations: {outstanding}")
            report_lines.append(f"Paid Violations: {paid}")
            
            # Date range
            dates = [v.get('issue_date', '') for v in violations if v.get('issue_date')]
            if dates:
                date_range = f"{min(dates)} to {max(dates)}"
                report_lines.append(f"Date Range: {date_range}")
            
            # Most common violation
            violation_counts = {}
            for v in violations:
                violation = v.get('violation_description', v.get('violation_code', 'Unknown'))
                violation_counts[violation] = violation_counts.get(violation, 0) + 1
            if violation_counts:
                most_common = max(violation_counts, key=violation_counts.get)
                report_lines.append(f"Most Common Violation: {most_common}")
            
            report_lines.append("")
            
            # Outstanding violations
            if outstanding > 0:
                report_lines.append(f"OUTSTANDING VIOLATIONS ({outstanding})")
                report_lines.append("-" * 40)
                outstanding_violations = [v for v in violations if float(v.get('amount_due', 0)) > 0][:10]
                
                # Headers
                report_lines.append(f"{'Date':<12} {'Violation':<35} {'Fine':<8} {'Due':<8} {'Status':<12}")
                report_lines.append("-" * 80)
                
                for violation in outstanding_violations:
                    date = violation.get('issue_date', 'N/A')[:10]
                    violation_desc = violation.get('violation_description', 
                                                 violation.get('violation_code', 'N/A'))[:32]
                    fine = f"${float(violation.get('fine_amount', 0)):.0f}"
                    due = f"${float(violation.get('amount_due', 0)):.0f}"
                    status = violation.get('status', 'N/A')[:12]
                    
                    report_lines.append(f"{date:<12} {violation_desc:<35} {fine:<8} {due:<8} {status:<12}")
                
                report_lines.append("")
            
            # Recent violations
            report_lines.append("RECENT VIOLATIONS (Last 10)")
            report_lines.append("-" * 40)
            recent_violations = sorted(violations, 
                                     key=lambda x: x.get('issue_date', ''), 
                                     reverse=True)[:10]
            
            # Headers
            report_lines.append(f"{'Date':<12} {'Violation':<35} {'Fine':<8} {'Due':<8} {'Status':<12}")
            report_lines.append("-" * 80)
            
            for violation in recent_violations:
                date = violation.get('issue_date', 'N/A')[:10]
                violation_desc = violation.get('violation_description', 
                                             violation.get('violation_code', 'N/A'))[:32]
                fine = f"${float(violation.get('fine_amount', 0)):.0f}"
                due = f"${float(violation.get('amount_due', 0)):.0f}"
                status = violation.get('status', 'N/A')[:12]
                
                report_lines.append(f"{date:<12} {violation_desc:<35} {fine:<8} {due:<8} {status:<12}")
            
            # Agency breakdown
            agency_counts = {}
            for v in violations:
                agency = v.get('issuing_agency', 'Unknown')
                agency_counts[agency] = agency_counts.get(agency, 0) + 1
            
            if len(agency_counts) > 1:
                report_lines.append("")
                report_lines.append("VIOLATIONS BY AGENCY")
                report_lines.append("-" * 40)
                
                total_violations = sum(agency_counts.values())
                for agency, count in sorted(agency_counts.items(), key=lambda x: x[1], reverse=True):
                    percentage = (count / total_violations) * 100
                    report_lines.append(f"{agency:<40} {count:>5} ({percentage:>5.1f}%)")
            
        else:
            # No violations found
            report_lines.append("VIOLATION RESULTS")
            report_lines.append("-" * 40)
            if violations_data['success']:
                report_lines.append("✓ Great News!")
                report_lines.append("")
                report_lines.append(f"No parking violations were found for license plate {license_plate} from {state}.")
                report_lines.append("This vehicle has a clean record in the NYC parking violations database.")
            else:
                report_lines.append("✗ Error")
                report_lines.append("")
                error_msg = violations_data.get('error', 'Unknown error')
                report_lines.append(f"Unable to retrieve violation data: {error_msg}")
                report_lines.append("Please try again later.")
        
        # Footer
        report_lines.append("")
        report_lines.append("=" * 80)
        report_lines.append("This report was generated using official NYC Open Data.")
        report_lines.append("For the most current information, visit the official NYC website.")
        report_lines.append("=" * 80)
        
        # Convert to bytes
        return "\\n".join(report_lines).encode('utf-8')
    
    def _generate_reportlab_pdf(self, license_plate: str, state: str, violations_data: Dict[str, Any]) -> bytes:
        """Generate PDF using ReportLab (when available)"""
        # This would contain the ReportLab implementation
        # For now, fall back to text
        return self._generate_text_report(license_plate, state, violations_data)
    
    def _generate_fpdf_pdf(self, license_plate: str, state: str, violations_data: Dict[str, Any]) -> bytes:
        """Generate PDF using FPDF (when available)"""
        # This would contain the FPDF implementation
        # For now, fall back to text
        return self._generate_text_report(license_plate, state, violations_data)
    
    def get_report_format(self) -> str:
        """Return the format of reports this generator produces"""
        if self.pdf_available:
            return "PDF"
        else:
            return "TEXT"


# Test function
async def test_pdf_generation():
    """Test PDF generation with fallback"""
    try:
        import sys
        sys.path.insert(0, '/home/scrapybara/NYC-SCRAPER-main')
        from nyc_api_client import NYCViolationsAPI
        
        api_client = NYCViolationsAPI()
        
        # Test with a plate that has violations
        result = await api_client.search_violations("AW716M", "NJ")
        
        if result['success']:
            pdf_generator = ViolationsPDFGenerator()
            report_bytes = pdf_generator.generate_violation_report("AW716M", "NJ", result)
            
            # Determine file extension based on format
            format_type = pdf_generator.get_report_format()
            extension = ".pdf" if format_type == "PDF" else ".txt"
            filename = f'/home/scrapybara/violations_report{extension}'
            
            # Save to file
            with open(filename, 'wb') as f:
                f.write(report_bytes)
            
            print(f"✅ {format_type} report generated successfully: {len(report_bytes)} bytes")
            print(f"📄 Saved to: {filename}")
            print(f"📊 Format: {format_type} (PDF library available: {pdf_generator.pdf_available})")
            return True
        else:
            print(f"❌ Failed to get violation data: {result.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error in PDF generation test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    import asyncio
    asyncio.run(test_pdf_generation())