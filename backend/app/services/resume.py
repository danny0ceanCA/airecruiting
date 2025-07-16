def generate_resume_text(client, student: dict, job: dict) -> str:
    """Create an HTML resume tailored to the student and job."""
    instructions = f"""
You are generating a professional resume in HTML format. Use the information
provided to craft a concise resume. Structure the document with <h2> section
headers and <ul> bullet lists. Include these sections:

1. **Name and Contact Information** - include email and phone.
2. **Professional Summary** - a short introduction of the candidate.
3. **Skills** - present as a bullet list.
4. **Experience** - bullet points for each relevant job or role.
5. **Education** - mention the education level.

Return only valid HTML using <h2> and <ul> elements. Do not include outer
<html> or <body> tags.

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
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": instructions}],
        temperature=0.4,
    )
    return resp.choices[0].message.content
