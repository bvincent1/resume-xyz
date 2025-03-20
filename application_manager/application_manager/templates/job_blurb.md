Given the following job description:
"""
{{ job_description }}
"""

and the following list of things I did at a company:
"""
{%- for task in job_tasks_list %}
- {{ task }}
{%- endfor %}
"""
write a few sentences that sums up my tasks such that they're relevant to the job without actually mentioning the posting or referring to it in any way using past tense