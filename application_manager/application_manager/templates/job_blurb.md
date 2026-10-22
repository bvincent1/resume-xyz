Given the following job description:
"""
{{ job_description }}
"""

and the following keywords from the posting:
"""
{{ job_analysis.keywords | join(', ') }}
"""

Use the get_job_history tool with company_key="{{ company_key }}" to fetch the list of things I did at the company.

write a few sentences that sums up my tasks such that they're relevant to the job without actually mentioning the posting or referring to it in any way using past tense. Plain text response only.
