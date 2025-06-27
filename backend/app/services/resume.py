def generate_resume_text(client, student: dict, job: dict) -> str:
    """Create a tailored job summary using OpenAI"""
    prompt = f"""
Analyze the student's skills, experience and interests below, then read the job title and description.
Write a clear and concise one page summary in plain professional language that:
- Describes what the job entails
- Explains why the student may be a good fit
- Mentions any areas where the student might need growth or preparation

Student Information:
Name: {student.get('first_name', '')} {student.get('last_name', '')}
Skills: {', '.join(student.get('skills', []))}
Interests: {student.get('interests', '')}
Experience Summary: {student.get('experience_summary', '')}

Job Title: {job.get('job_title')}
Job Description: {job.get('job_description')}
Required Skills: {', '.join(job.get('desired_skills', []))}
"""

    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return resp.choices[0].message.content
