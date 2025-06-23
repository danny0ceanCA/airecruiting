export function generateResumeContent(student, job, doc) {
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();

  // Header bar
  doc.setFillColor(0, 32, 96);
  doc.rect(0, 0, pageWidth, 25, 'F');
  doc.setTextColor(255, 255, 255);
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(16);
  doc.text('TalenMatch AI', 10, 15);
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  doc.text('Intelligence that powers every placement.', 10, 22);

  // Student information
  doc.setTextColor(0, 0, 0);
  const startY = 35;
  doc.setFont('helvetica', 'bold');
  doc.setFontSize(12);
  const name = `${student.first_name || ''} ${student.last_name || ''}`.trim();
  if (name) {
    doc.text(name, 10, startY);
  }
  doc.setFont('helvetica', 'normal');
  doc.setFontSize(10);
  if (student.email) {
    doc.text(student.email, 10, startY + 7);
  }

  // Job information
  let jobY = startY + 20;
  if (job && job.job_title) {
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(12);
    doc.text(job.job_title, 10, jobY);
    jobY += 7;
  }
  if (job && job.job_description) {
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    doc.text(doc.splitTextToSize(job.job_description, pageWidth - 20), 10, jobY);
  }

  // Footer watermark
  doc.setFont('helvetica', 'normal');
  doc.setTextColor(150, 150, 150);
  doc.setFontSize(9);
  doc.text('Tailored by TalenMatch AI', pageWidth / 2, pageHeight - 10, { align: 'center' });
}

