Given the following job description:
"""
{{ job_description }}
"""

and the following job histories:

{%- for job in job_histories %}
"""
{{job-}}
"""
{%- endfor %}

write a few sentences summarizing my work experience and why I'm perfect for this position, keeping it under 4 sentences
