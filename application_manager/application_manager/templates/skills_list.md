Given this list of all my {{ skill_type }} skills:
"""
{% for skill in skills_list %}
{{-skill-}}
{%- endfor %}"""

pick the {{ skill_count }} most relevant as a comma separated list for the following job description:
"""
{{ job_description }}
"""
