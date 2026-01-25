"""
simulation/infrastructure/expansion/cost_recovery_tracker.py

Infrastructure cost recovery and ROI tracking.

This module tracks the costs associated with infrastructure investments and the revenue generated
from charging sessions. It calculates key financial metrics such as return on investment (ROI),
payback periods, and profitability to aid in strategic decision-making for infrastructure expansion.

"""

from __future__ import annotations
from typing import Dict
import logging

logger = logging.getLogger(__name__)


class CostRecoveryTracker:
    """Tracks infrastructure investment and revenue."""
    
    def __init__(self):
        """Initialize cost recovery tracker."""
        self.total_investment = 0.0
        self.total_revenue = 0.0
        self.operating_costs = 0.0
        
        logger.info("CostRecoveryTracker initialized")
    
    def record_investment(self, amount: float) -> None:
        """Record infrastructure investment (CAPEX)."""
        self.total_investment += amount
        logger.debug(f"Investment recorded: £{amount:,.0f}")
    
    def record_revenue(self, amount: float) -> None:
        """Record charging revenue."""
        self.total_revenue += amount
        
        # Operating costs are 10% of revenue
        self.operating_costs += amount * 0.10
    
    def get_metrics(self) -> Dict:
        """Get cost recovery metrics."""
        profit = self.total_revenue - self.operating_costs
        roi = (self.total_revenue / self.total_investment * 100) if self.total_investment > 0 else 0
        
        # Payback period (years)
        annual_revenue = self.total_revenue  # Assume current rate
        payback = (self.total_investment / annual_revenue) if annual_revenue > 0 else float('inf')
        
        return {
            'total_investment': self.total_investment,
            'total_revenue': self.total_revenue,
            'operating_costs': self.operating_costs,
            'profit': profit,
            'roi_percentage': roi,
            'payback_years': payback,
            'break_even': profit >= 0,
        }