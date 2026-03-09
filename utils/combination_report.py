"""
utils/combination_report.py

Agent combination report generator integrated with Streamlit.
Outputs reports to RTD_SIM/logs/ directory.
"""

from pathlib import Path
from typing import List, Tuple, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def generate_combination_report(
    user_story_ids: List[str],
    job_story_ids: List[str],
    output_dir: Path = None
) -> Path:
    """
    Generate comprehensive report of user+job combinations.
    
    Args:
        user_story_ids: List of available user personas
        job_story_ids: List of available job types
        output_dir: Directory to save report (default: logs/)
    
    Returns:
        Path to generated report file
    """
    from agent.story_compatibility import (
        is_compatible,
        filter_compatible_combinations,
        COMPATIBLE_USERS_FOR_JOB,
        get_missing_whitelists
    )
    
    # Setup output directory
    if output_dir is None:
        output_dir = Path('logs')
    output_dir.mkdir(exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = output_dir / f'combination_report_{timestamp}.txt'
    
    # Generate report
    with open(report_path, 'w') as f:
        # Header
        f.write("="*100 + "\n")
        f.write("RTD_SIM AGENT COMBINATION REPORT\n")
        f.write("="*100 + "\n")
        f.write(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"\nUser Stories: {len(user_story_ids)}\n")
        f.write(f"Job Stories: {len(job_story_ids)}\n")
        f.write(f"Total Possible Combinations: {len(user_story_ids) * len(job_story_ids)}\n")
        f.write("="*100 + "\n\n")
        
        # Get compatible combinations
        compatible = filter_compatible_combinations(user_story_ids, job_story_ids)
        blocked_count = (len(user_story_ids) * len(job_story_ids)) - len(compatible)
        
        f.write(f"✅ ALLOWED Combinations: {len(compatible)}\n")
        f.write(f"❌ BLOCKED Combinations: {blocked_count}\n")
        f.write(f"📊 Filter Efficiency: {blocked_count / (len(user_story_ids) * len(job_story_ids)) * 100:.1f}% blocked\n\n")
        
        # Section 1: Missing whitelists
        f.write("="*100 + "\n")
        f.write("⚠️  JOBS WITHOUT WHITELISTS (CRITICAL ISSUE!)\n")
        f.write("="*100 + "\n\n")
        
        missing = get_missing_whitelists(job_story_ids)
        if missing:
            f.write(f"🚨 {len(missing)} jobs are missing whitelists - these will BLOCK all users!\n\n")
            for job in sorted(missing):
                f.write(f"  ⚠️  {job}\n")
        else:
            f.write("  ✅ All jobs have whitelists defined!\n")
        f.write("\n")
        
        # Section 2: Breakdown by job type
        f.write("="*100 + "\n")
        f.write("DETAILED BREAKDOWN BY JOB TYPE\n")
        f.write("="*100 + "\n\n")
        
        for job in sorted(job_story_ids):
            f.write(f"📋 JOB: {job}\n")
            f.write("-"*100 + "\n")
            
            allowed_users = [u for u in user_story_ids if is_compatible(u, job)]
            blocked_users = [u for u in user_story_ids if not is_compatible(u, job)]
            
            if allowed_users:
                f.write(f"  ✅ ALLOWED ({len(allowed_users)}):\n")
                for user in sorted(allowed_users):
                    f.write(f"      - {user}\n")
            else:
                f.write(f"  ✅ ALLOWED: NONE (job has no whitelist)\n")
            
            if blocked_users:
                f.write(f"  ❌ BLOCKED ({len(blocked_users)}):\n")
                for user in sorted(blocked_users):
                    f.write(f"      - {user}\n")
            
            f.write("\n")
        
        # Section 3: Breakdown by user type
        f.write("="*100 + "\n")
        f.write("BREAKDOWN BY USER PERSONA\n")
        f.write("="*100 + "\n\n")
        
        for user in sorted(user_story_ids):
            f.write(f"👤 USER: {user}\n")
            f.write("-"*100 + "\n")
            
            allowed_jobs = [j for j in job_story_ids if is_compatible(user, j)]
            blocked_jobs = [j for j in job_story_ids if not is_compatible(user, j)]
            
            f.write(f"  ✅ CAN DO ({len(allowed_jobs)}):\n")
            for job in sorted(allowed_jobs):
                f.write(f"      - {job}\n")
            
            f.write(f"  ❌ CANNOT DO ({len(blocked_jobs)}):\n")
            if len(blocked_jobs) <= 10:
                for job in sorted(blocked_jobs):
                    f.write(f"      - {job}\n")
            else:
                f.write(f"      (Too many to list: {len(blocked_jobs)} jobs)\n")
            
            f.write("\n")
        
        # Section 4: Potentially problematic combinations
        f.write("="*100 + "\n")
        f.write("🚨 SANITY CHECK: Potentially Odd Combinations\n")
        f.write("="*100 + "\n\n")
        
        f.write("These combinations are ALLOWED but may need review:\n\n")
        
        # Heuristics for odd combinations
        odd_patterns = [
            ('tourist', ['freight', 'delivery', 'warehouse', 'construction', 'hgv', 'truck']),
            ('budget_student', ['freight', 'hgv', 'truck', 'warehouse']),
            ('disabled_commuter', ['freight', 'hgv', 'truck', 'construction']),
            ('concerned_parent', ['freight', 'hgv', 'warehouse']),
            ('freight_operator', ['tourist', 'scenic', 'leisure']),
        ]
        
        found_odd = False
        for user, job_keywords in odd_patterns:
            if user not in user_story_ids:
                continue
            
            for job in job_story_ids:
                if any(keyword in job.lower() for keyword in job_keywords):
                    if is_compatible(user, job):
                        f.write(f"  🚨 {user} + {job}\n")
                        found_odd = True
        
        if not found_odd:
            f.write("  ✅ No obviously odd combinations found!\n")
        
        f.write("\n")
        
        # Section 5: Summary statistics
        f.write("="*100 + "\n")
        f.write("SUMMARY STATISTICS\n")
        f.write("="*100 + "\n\n")
        
        # Jobs per user
        jobs_per_user = {}
        for user in user_story_ids:
            count = sum(1 for job in job_story_ids if is_compatible(user, job))
            jobs_per_user[user] = count
        
        f.write("Jobs available per user persona:\n")
        for user, count in sorted(jobs_per_user.items(), key=lambda x: x[1], reverse=True):
            pct = (count / len(job_story_ids)) * 100
            f.write(f"  {user:30s} {count:3d} jobs ({pct:5.1f}%)\n")
        
        f.write("\n")
        
        # Users per job
        users_per_job = {}
        for job in job_story_ids:
            count = sum(1 for user in user_story_ids if is_compatible(user, job))
            users_per_job[job] = count
        
        f.write("Users allowed per job type:\n")
        for job, count in sorted(users_per_job.items(), key=lambda x: x[1], reverse=True):
            pct = (count / len(user_story_ids)) * 100 if len(user_story_ids) > 0 else 0
            f.write(f"  {job:40s} {count:2d} users ({pct:5.1f}%)\n")
        
        f.write("\n")
        f.write("="*100 + "\n")
        f.write("END OF REPORT\n")
        f.write("="*100 + "\n")
    
    logger.info(f"✅ Combination report generated: {report_path}")
    return report_path


def generate_quick_summary(
    user_story_ids: List[str],
    job_story_ids: List[str]
) -> Dict[str, any]:
    """
    Generate quick summary statistics for display in Streamlit.
    
    Args:
        user_story_ids: List of user personas
        job_story_ids: List of job types
    
    Returns:
        Dictionary with summary statistics
    """
    from agent.story_compatibility import (
        filter_compatible_combinations,
        get_missing_whitelists
    )
    
    compatible = filter_compatible_combinations(user_story_ids, job_story_ids)
    total = len(user_story_ids) * len(job_story_ids)
    blocked = total - len(compatible)
    missing = get_missing_whitelists(job_story_ids)
    
    return {
        'total_combinations': total,
        'allowed_combinations': len(compatible),
        'blocked_combinations': blocked,
        'filter_efficiency_pct': (blocked / total * 100) if total > 0 else 0,
        'missing_whitelists': len(missing),
        'missing_whitelist_jobs': missing
    }