import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import JobPosting from './JobPosting';
import { BrowserRouter } from 'react-router-dom';
import api from './api';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = { get: jest.fn(), post: jest.fn(), create: jest.fn() };
  mockAxios.create.mockReturnValue(mockAxios);
  return mockAxios;
});

jest.mock('./utils/loadGoogleMaps', () => jest.fn(cb => cb && cb()));

test('assigning and unassigning students keeps badge and table in sync', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4iLCJzdWIiOiJhZG1pbkBleGFtcGxlLmNvbSJ9.signature';
  localStorage.setItem('token', token);

  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    if (url === '/jobs') {
      return Promise.resolve({
        data: {
          jobs: [
            {
              job_code: 'J1',
              job_title: 'Job 1',
              required_license: '',
              source: '',
              min_pay: 0,
              max_pay: 0,
              assigned_students: [],
              placed_students: [],
            },
          ],
        },
      });
    }
    if (url === '/has-match/J1') {
      return Promise.resolve({ data: { has_match: true } });
    }
    if (url === '/match/J1') {
      return Promise.resolve({
        data: {
          matches: [
            {
              first_name: 'Stu',
              last_name: 'Dent',
              email: 'stu@example.com',
              score: 0.9,
              status: null,
            },
          ],
        },
      });
    }
    return Promise.resolve({ data: {} });
  });

  api.post.mockImplementation((url) => {
    if (url === '/assign') return Promise.resolve({});
    if (url === '/reject-assigned') return Promise.resolve({});
    return Promise.resolve({});
  });

  render(
    <BrowserRouter>
      <JobPosting />
    </BrowserRouter>
  );

  const expand = await screen.findByText('+');
  fireEvent.click(expand);

  const checkbox = await screen.findByRole('checkbox');
  fireEvent.click(checkbox);

  fireEvent.click(await screen.findByText(/Mark Selected as Interested/));

  const badge = await screen.findByText('1');
  fireEvent.click(badge);

  expect(await screen.findByText('stu@example.com')).toBeInTheDocument();

  fireEvent.click(screen.getByText('Not Interested'));

  await waitFor(() => {
    expect(screen.queryByText('stu@example.com')).not.toBeInTheDocument();
    expect(screen.queryByText('1')).not.toBeInTheDocument();
  });

  localStorage.clear();
});
