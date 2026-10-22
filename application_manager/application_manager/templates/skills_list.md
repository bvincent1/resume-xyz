Use the get_skill_list tool with skill_type="{{ skill_type }}" to fetch my {{ skill_type }} skills.

Given the following job description:
"""
{{ job_description }}
"""

and the following keywords from the posting:
"""
{{ job_analysis.keywords | join(', ') }}
"""

pick the most important skills from the job description and return a list of AT MOST 4 skills such that at least 2 intersect with my skills list. You're allowed to use skills from the job posting if they're similar to my skills from the skills list.
