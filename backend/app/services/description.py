"""Service to generate a job description tailored for a student."""

def generate_description_text(client, student: dict, job: dict) -> str:
    prompt = f"""
Write a concise job description for the following position. Tailor it to the student's background when relevant.

Student Information:
Name: {student.get('first_name', '')} {student.get('last_name', '')}
Skills: {', '.join(student.get('skills', []))}

Job Title: {job.get('job_title')}
Current Description: {job.get('job_description')}
Required Skills: {', '.join(job.get('desired_skills', []))}

Return a short, well formatted paragraph.
"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content
