"""
Prompt templates for Recruitment/ATS Agent.
"""

def get_jd_generation_prompt(role: str) -> str:
    """Prompt for generating a professional Job Description."""
    return f"""Write a professional, detailed job description for the role: {role}.
    Include the following sections:
    1. Role Summary
    2. Key Responsibilities
    3. Required Technical Skills
    4. Soft Skills & Preferred Qualifications
    5. Educational Requirements

    Format the output in clear Markdown.
    """


def get_resume_analysis_prompt(resume_text: str, jd_text: str) -> str:
    """Full prompt for detailed ATS scoring of a single resume against a JD.
    Ported from original openAiService.js — returns 15+ structured fields.
    """
    return f"""Analyze the provided resume against the job description and generate a detailed evaluation report.

    Input:
    Resume Text: "{resume_text[:15000]}"
    Job Description: "{jd_text[:3000]}"

    Evaluation Guidelines:
    1. Skills Matching
        - First extract ALL skills from resume (both technical and soft skills)
        - Then extract ALL required skills from job description
        - For each skill found in resume:
          * Check if it appears in job description
          * Note the context and proficiency level mentioned
          * Consider skill variations (e.g., "React.js" = "ReactJS")
          * Mark as true if found in job description, false if not
        - List all skills from resume regardless of job description match
        - Ensure no skills are missed even if they don't match

    2. Content Evaluation
    - Identify gaps and irrelevant content
    - Penalize vague or unrelated experiences
    - Evaluate clarity and specificity of achievements
    - Check for quantifiable results and impact

    3. Project/Internship Analysis
    - Match projects strictly based on JD relevance
    - Evaluate technology stack alignment
    - Check implementation context
    - Verify outcome relevance

    4. Resume Quality Metrics
    - Grammar and professionalism (independent of JD)
    - Structure and formatting
    - Content organization
    - Action verb usage
    - Quantifiable achievements

    Scoring Guidelines:
    - JScore (0-100): Strict evaluation of JD alignment
      70-100: Excellent match with specific skills and experience
      40-69: Partial match with some relevant experience
      0-39: Poor match with significant gaps

    - GScore (0-100): Overall resume quality
      70-100: Professional, well-structured, clear achievements
      40-69: Decent structure, needs minor improvements
      0-39: Major improvements needed

    Required Output Format (JSON only):
    {{
        "Job Title Match": "Matched/Not Matched",
        "Skills": {{
            "TechnicalSkills": {{"skill_name": true_or_false}},
            "SoftSkills": {{"skill_name": true_or_false}}
        }},
        "Suggested Skills": ["skill1", "skill2"],
        "Matched Projects And Internships": [
            {{
                "Project": "title",
                "Description": "alignment explanation"
            }}
        ],
        "Rephrased Projects And Internships": [
            {{
                "Original": "text",
                "Rephrased": ["point1", "point2", "point3"]
            }}
        ],
        "Resume Improvement Suggestions": ["suggestion1", "suggestion2"],
        "Grammatical Check": "detailed review",
        "Project Title Description Check": [
            {{
                "Project": "title",
                "Status": "Matched/Not Matched",
                "Explanation": "consistency review"
            }}
        ],
        "Recruiter Tips": {{
            "Suggestions": ["tip1", "tip2", "tip3"],
            "Word Count": "detailed recommendation",
            "wordsToAvoid": {{
                "word1": "alternative",
                "word2": "alternative"
            }}
        }},
        "JScore": number,
        "GScore": number
    }}

    Important:
    - Provide only the JSON response
    - Maintain exact key names as shown
    - Ensure all values are properly formatted
    - No additional explanations or text outside JSON structure"""


def get_batch_score_prompt(resume_text: str, jd_text: str) -> str:
    """Enhanced prompt for batch processing — returns rich candidate profile for Excel."""
    return f"""I will provide you with two inputs:
- Resume Text: A candidate's resume in text format.
- Job Description (JD): A job listing or description that the candidate is applying to.

Your task is to **evaluate strictly** the resume based on the JD and return a detailed JSON object.

Return ONLY the JSON object with NO explanation or any other text:

{{
    "name": "Candidate's Full Name",
    "email": "Candidate's Email (or 'Not Found')",
    "phone": "Candidate's Phone (or 'Not Found')",
    "experience_level": "Fresher / Junior (1-3 yrs) / Mid (3-6 yrs) / Senior (6-10 yrs) / Lead (10+ yrs)",
    "total_experience": "e.g. 4 years 2 months (or 'Not Specified')",
    "education": "Highest degree and institution (e.g. B.Tech CS, IIT Delhi)",
    "top_matching_skills": ["skill1", "skill2", "skill3", "skill4", "skill5"],
    "missing_critical_skills": ["skill1", "skill2", "skill3"],
    "key_strengths": "1-2 sentence summary of candidate's strongest qualifications relevant to JD",
    "key_gaps": "1-2 sentence summary of major gaps or concerns",
    "jScore": JD_alignment_score_0_to_100,
    "gScore": General_resume_quality_score_0_to_100,
    "recommendation": "Strong Hire / Hire / Maybe / Reject"
}}

Evaluation Guidelines:
- Match skills contextually, not just by keyword. Only mark a skill as present if it matches the context required by the JD.
- Be **extremely strict** — vague or irrelevant content should significantly lower scores.
- top_matching_skills: List up to 5 skills that match between resume and JD.
- missing_critical_skills: List up to 3 skills from JD that are completely absent from the resume.
- recommendation: Based on jScore:
  * 70+: "Strong Hire"
  * 55-69: "Hire" 
  * 40-54: "Maybe"
  * Below 40: "Reject"

Scoring Guidelines:
- JScore (0-100): Strict evaluation of JD alignment
  70-100: Excellent match with specific skills and experience
  40-69: Partial match with some relevant experience
  0-39: Poor match with significant gaps

- GScore (0-100): Overall resume quality
  70-100: Professional, well-structured, clear achievements
  40-69: Decent structure, needs minor improvements
  0-39: Major improvements needed

Below is the Resume Text: "{resume_text[:15000]}"
Below is the Job Description: "{jd_text[:3000]}"
"""
