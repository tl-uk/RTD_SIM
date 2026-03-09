"""
ui/tabs/combination_report_tab.py

Streamlit tab for viewing and generating agent combination reports.
Integrates with main streamlit_app.py.
"""

import streamlit as st
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def render_combination_report_tab():
    """
    Render the combination report tab in Streamlit.
    
    Shows:
    - Quick summary statistics
    - Generate full report button
    - View recent reports
    """
    st.header("🔍 Agent Combination Report")
    
    st.markdown("""
    This tool validates that user personas and job types are sensibly combined.
    It helps identify nonsensical combinations like "tourist + freight_delivery".
    """)
    
    # Check if required modules are available
    try:
        from agent.user_stories import UserStoryParser
        from agent.job_stories import JobStoryParser
        from utils.combination_report import generate_combination_report, generate_quick_summary
        from agent.story_compatibility import get_missing_whitelists
    except ImportError as e:
        st.error(f"❌ Required modules not found: {e}")
        st.info("Make sure story_compatibility.py and combination_report.py are installed.")
        return
    
    # Load user and job stories
    try:
        user_parser = UserStoryParser()
        job_parser = JobStoryParser()
        
        user_story_ids = user_parser.list_available_stories()
        job_story_ids = job_parser.list_available_stories()
    except Exception as e:
        st.error(f"❌ Error loading stories: {e}")
        return
    
    # Display quick summary
    st.subheader("📊 Quick Summary")
    
    try:
        summary = generate_quick_summary(user_story_ids, job_story_ids)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                "Total Combinations",
                summary['total_combinations']
            )
        
        with col2:
            st.metric(
                "✅ Allowed",
                summary['allowed_combinations']
            )
        
        with col3:
            st.metric(
                "❌ Blocked",
                summary['blocked_combinations'],
                delta=f"{summary['filter_efficiency_pct']:.1f}% filtered"
            )
        
        with col4:
            status = "⚠️" if summary['missing_whitelists'] > 0 else "✅"
            st.metric(
                "Missing Whitelists",
                summary['missing_whitelists'],
                delta=status
            )
        
        # Show missing whitelists warning
        if summary['missing_whitelists'] > 0:
            st.warning(
                f"⚠️ **{summary['missing_whitelists']} job types have no whitelist!** "
                f"These will block ALL users. Jobs: {', '.join(summary['missing_whitelist_jobs'][:5])}"
                + (f" and {len(summary['missing_whitelist_jobs']) - 5} more..." 
                   if len(summary['missing_whitelist_jobs']) > 5 else "")
            )
    except Exception as e:
        st.error(f"Error generating summary: {e}")
    
    st.markdown("---")
    
    # Generate full report section
    st.subheader("📄 Generate Full Report")
    
    st.markdown("""
    Generate a comprehensive report that includes:
    - Detailed breakdown by job type (who can do each job)
    - Breakdown by user persona (what each person can do)
    - Sanity checks for odd combinations
    - Summary statistics
    """)
    
    # Output directory selection
    output_dir = st.text_input(
        "Output Directory",
        value="logs",
        help="Directory to save the report (relative to RTD_SIM root)"
    )
    
    if st.button("🔍 Generate Full Report", type="primary"):
        with st.spinner("Generating report..."):
            try:
                report_path = generate_combination_report(
                    user_story_ids,
                    job_story_ids,
                    output_dir=Path(output_dir)
                )
                
                st.success(f"✅ Report generated successfully!")
                st.info(f"📁 Report saved to: `{report_path}`")
                
                # Show file preview
                with st.expander("📄 Preview Report (first 100 lines)"):
                    with open(report_path, 'r') as f:
                        lines = f.readlines()
                        preview = ''.join(lines[:100])
                        st.code(preview, language='text')
                
                # Download button
                with open(report_path, 'r') as f:
                    st.download_button(
                        label="📥 Download Report",
                        data=f.read(),
                        file_name=report_path.name,
                        mime='text/plain'
                    )
                
            except Exception as e:
                st.error(f"❌ Error generating report: {e}")
                logger.exception("Report generation failed")
    
    st.markdown("---")
    
    # Recent reports section
    st.subheader("📚 Recent Reports")
    
    try:
        logs_dir = Path(output_dir)
        if logs_dir.exists():
            report_files = sorted(
                logs_dir.glob('combination_report_*.txt'),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            
            if report_files:
                st.markdown(f"Found {len(report_files)} report(s):")
                
                for report_file in report_files[:5]:  # Show last 5
                    with st.expander(f"📄 {report_file.name}"):
                        file_size = report_file.stat().st_size
                        mod_time = report_file.stat().st_mtime
                        
                        st.markdown(f"**Size:** {file_size:,} bytes")
                        st.markdown(f"**Modified:** {Path(report_file).stat().st_mtime}")
                        
                        with open(report_file, 'r') as f:
                            st.download_button(
                                label="📥 Download",
                                data=f.read(),
                                file_name=report_file.name,
                                mime='text/plain',
                                key=f"download_{report_file.name}"
                            )
            else:
                st.info("No reports found. Generate one above!")
        else:
            st.info(f"Output directory `{output_dir}` does not exist yet.")
    
    except Exception as e:
        st.error(f"Error listing reports: {e}")
    
    # Help section
    with st.expander("ℹ️ Help & Documentation"):
        st.markdown("""
        ### How This Works
        
        The combination report validates that user personas (WHO) and job types (WHAT) 
        make sense together using a **whitelist approach**.
        
        **Whitelist System:**
        - Each job type has a list of user personas that can do it
        - If a persona is not in the whitelist → combination is BLOCKED
        - This prevents nonsensical agents like "tourist driving freight truck"
        
        **What Gets Blocked:**
        - ❌ `tourist + freight_delivery` (tourists don't drive trucks)
        - ❌ `budget_student + hgv_construction` (students don't drive construction HGVs)
        - ❌ `concerned_parent + waste_collection` (parents aren't waste collectors)
        
        **What's Allowed:**
        - ✅ `freight_operator + freight_delivery` (professional driver)
        - ✅ `tourist + tourist_scenic_rail` (tourist activity)
        - ✅ `concerned_parent + shopping_trip` (parent errand)
        
        ### Missing Whitelists
        
        If a job type has NO whitelist defined, it will block ALL users by default.
        This is a safety measure to prevent nonsensical combinations.
        
        **Fix:** Add the job type to `story_compatibility.py` with appropriate users.
        
        ### Report Sections
        
        1. **Jobs Without Whitelists** - Critical issues that need fixing
        2. **Breakdown by Job** - For each job, who can do it
        3. **Breakdown by User** - For each persona, what they can do
        4. **Sanity Check** - Potentially odd combinations that slipped through
        5. **Summary Statistics** - Distribution of jobs/users
        """)


# Integration helper function for streamlit_app.py
def add_combination_report_tab():
    """
    Helper function to add this tab to main streamlit app.
    
    Usage in streamlit_app.py:
        from ui.combination_report_tab import add_combination_report_tab
        
        tabs = st.tabs(["Overview", "Analytics", "Combination Report", ...])
        
        with tabs[2]:  # Combination Report tab
            add_combination_report_tab()
    """
    render_combination_report_tab()