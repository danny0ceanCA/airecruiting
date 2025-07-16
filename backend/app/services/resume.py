def generate_resume_text(client, student: dict, job: dict) -> str:
    """Create an HTML resume tailored to the student and job."""
    instructions = f"""
You are generating a professional resume in HTML format. Use the information
provided to craft a short resume with these sections:

1. **Name and Contact Information** - include email and phone.
2. **Skills** - highlight relevant skills from the student profile.
3. **Experience Summary / Job History** - summarise the student's background
   and how it relates to the assigned job.

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

Return only valid HTML.
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": instructions}],
        temperature=0.4,
    )
    return resp.choices[0].message.content
