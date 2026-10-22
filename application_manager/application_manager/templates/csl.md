Given the following job description:
"""
{{ job_description }}
"""

and the following keywords already extracted from it:
"""
{{ job_analysis.keywords | join(', ') }}
"""

Return a list of the posting's keywords, including related terms or keywords.
