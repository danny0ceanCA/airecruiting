def generate_resume_text(client, student: dict, job: dict) -> str:
    """Create a tailored job summary using OpenAI"""
    instructions = f"""
You are a career advisor assistant. Create a personalized job summary for a student who has been assigned a job opportunity. Your task is to:

1. Summarize what the assigned job entails in plain, student-friendly language.
2. Explain why the student may be a good fit based on their background, skills, and interests.
3. Gently mention areas the student might need to work on or prepare for before starting.

Respond with professional, friendly language. Do not format as a resume. Write clearly in paragraph form using plain language. Your audience is the student and their career advisor.

Student Profile:
Name: {student.get('first_name', '')} {student.get('last_name', '')}
Email: {student.get('email', '')}
Phone: {student.get('phone', '')}
Education Level: {student.get('education_level', '')}
Skills: {', '.join(student.get('skills', []))}
Experience Summary: {student.get('experience_summary', '')}
Interests: {student.get('interests', '')}

Assigned Job:
Title: {job.get('job_title')}
Description: {job.get('job_description')}
Desired Skills: {', '.join(job.get('desired_skills', []))}

Begin with a short 1–2 sentence job summary, followed by a paragraph explaining the student’s fit, and end with a short paragraph highlighting potential preparation tips.
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": instructions}],
        temperature=0.4,
    )
    return resp.choices[0].message.content
