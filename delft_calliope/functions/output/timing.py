"""
Timing Infrastructure for run_analysis.py

This module provides a context manager for tracking execution times
of workflow steps and utilities for displaying timing summaries.
"""

import time
import pandas as pd


# Global dictionary to store execution times for each workflow step
execution_times = {}


class Timer:
    """
    Context manager for timing code sections.
    
    Records execution time of a code block and stores it in the
    global execution_times dictionary with the given label. Also prints
    the elapsed time immediately after the block completes.
    
    Parameters
    ----------
    name : str
        Label for the timed operation. Used as key in execution_times.
    
    Examples
    --------
    >>> with Timer("data_loading"):
    ...     load_data()
     data_loading: 12.345s
    """
    
    def __init__(self, name):
        self.name = name
    
    def __enter__(self):
        self.start = time.perf_counter()
        return self
    
    def __exit__(self, *args):
        self.end = time.perf_counter()
        elapsed = self.end - self.start
        execution_times[self.name] = elapsed
        print(f" {self.name}: {elapsed:.3f}s")


def print_timing_summary():
    """
    Print comprehensive timing analysis with percentage breakdown.
    
    Creates a pandas DataFrame from the execution_times dictionary
    showing each operation's time and percentage of total execution time,
    sorted by duration in descending order.
    """
    if execution_times:
        timing_df = pd.DataFrame({
            'Operation': list(execution_times.keys()),
            'Time (s)': list(execution_times.values())
        })
        timing_df['% of Total'] = (timing_df['Time (s)'] / timing_df['Time (s)'].sum() * 100).round(2)
        timing_df = timing_df.sort_values('Time (s)', ascending=False)
        
        print("\n" + "="*80)
        print("EXECUTION TIME SUMMARY")
        print("="*80)
        print(timing_df.to_string(index=False))
        print("="*80)
        print(f"Total Execution Time: {timing_df['Time (s)'].sum():.3f}s")
        print("="*80 + "\n")
    else:
        print("No timing data collected.")
