Use the get_work_summaries tool to fetch my finished work summaries.

Given the following job description:
"""
{{ job_description }}
"""

and the following keywords from the posting:
"""
{{ job_analysis.keywords | join(', ') }}
"""

write a few sentences summarizing my work experience and why I'm perfect for this position, keeping it under 4 sentences.
