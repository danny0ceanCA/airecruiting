def generate_resume_text(client, student: dict, job: dict) -> str:
    """Create a resume using OpenAI"""
    prompt = f"""
Write a professional resume for the following student, tailored to the job description below.

Student Information:
Name: {student.get('first_name', '')} {student.get('last_name', '')}
Email: {student.get('email', '')}
Skills: {', '.join(student.get('skills', []))}

Job Title: {job.get('job_title')}
Job Description: {job.get('job_description')}
Required Skills: {', '.join(job.get('desired_skills', []))}

The resume should be concise, modern, and use a consistent format.
"""

    resp = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content
