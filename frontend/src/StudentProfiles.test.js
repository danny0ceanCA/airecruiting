import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { act } from 'react';
import StudentProfiles from './StudentProfiles';
import { BrowserRouter } from 'react-router-dom';
import api from './api';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = { get: jest.fn(), post: jest.fn(), create: jest.fn() };
  mockAxios.create.mockReturnValue(mockAxios);
  return mockAxios;
});

jest.mock('./utils/loadGoogleMaps', () => jest.fn(cb => cb && cb()));

beforeEach(() => {
  localStorage.setItem('studentTourSeen', 'true');
  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    return Promise.resolve({ data: { students: [] } });
  });
});

test('renders StudentProfiles without errors', () => {
  expect(() => {
    render(
      <BrowserRouter>
        <StudentProfiles />
      </BrowserRouter>
    );
  }).not.toThrow();
});

test('displays student count in tab bar', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature';
  localStorage.setItem('token', token);
  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    return Promise.resolve({
      data: {
        students: [
          {
            first_name: 'A',
            last_name: 'B',
            email: 'a@example.com',
            city: 'City',
            state: 'ST',
            institutional_code: 'ABC',
            license: '',
            assigned_job_count: 0,
            placed_jobs: 0
          },
          {
            first_name: 'C',
            last_name: 'D',
            email: 'c@example.com',
            city: 'City',
            state: 'ST',
            institutional_code: 'ABC',
            license: '',
            assigned_job_count: 0,
            placed_jobs: 0
          }
        ]
      }
    });
  });
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  expect(await screen.findByTestId('student-count')).toHaveTextContent('Student Profiles: 2');
  localStorage.clear();
});

test('opens notes history modal when View Notes clicked', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature';
  localStorage.setItem('token', token);
  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    if (url === '/students/s@example.com/jobs') {
      return Promise.resolve({
        data: {
          jobs: [
            {
              job_code: 'J1',
              job_title: 'Job 1',
              status: 'open',
              notes: [{ text: 'Test note' }]
            }
          ]
        }
      });
    }
    return Promise.resolve({
      data: {
        students: [
          {
            first_name: 'F',
            last_name: 'L',
            email: 's@example.com',
            city: 'City',
            state: 'ST',
            institutional_code: 'ABC',
            assigned_job_count: 1,
            placed_jobs: 0,
            assigned_job_code: 'J1'
          }
        ]
      }
    });
  });
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  const expand = await screen.findByTitle('Expand');
  fireEvent.click(expand);
  expect(api.get).toHaveBeenCalledWith('/students/s@example.com/jobs', {
    headers: { Authorization: `Bearer ${token}` }
  });
  const viewNotes = await screen.findByText(/View Notes/);
  fireEvent.click(viewNotes);
  expect(await screen.findByText('Test note')).toBeInTheDocument();
  fireEvent.click(screen.getByText('X'));
  await waitFor(() => {
    expect(screen.queryByText('Test note')).not.toBeInTheDocument();
  });
  localStorage.clear();
});

test('loads jobs on demand when expanding a student', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature';
  localStorage.setItem('token', token);
  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    if (url === '/students/s@example.com/jobs') {
      return Promise.resolve({
        data: { jobs: [{ job_code: 'J1', job_title: 'Job 1', status: 'open' }] }
      });
    }
    return Promise.resolve({
      data: {
        students: [
          {
            first_name: 'F',
            last_name: 'L',
            email: 's@example.com',
            city: 'City',
            state: 'ST',
            institutional_code: 'ABC',
            assigned_job_count: 1,
            placed_jobs: 0,
            assigned_job_code: 'J1'
          }
        ]
      }
    });
  });
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  expect(screen.queryByText('Job 1')).not.toBeInTheDocument();
  const expand = await screen.findByTitle('Expand');
  fireEvent.click(expand);
  expect(api.get).toHaveBeenCalledWith('/students/s@example.com/jobs', {
    headers: { Authorization: `Bearer ${token}` }
  });
  expect(await screen.findByText('Job 1')).toBeInTheDocument();
  localStorage.clear();
});

test('deduplicates students from multiple payloads', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature';
  localStorage.setItem('token', token);

  const student = {
    first_name: 'A',
    last_name: 'B',
    email: 'a@example.com',
    city: 'City',
    state: 'ST',
    institutional_code: 'ABC',
    license: '',
    assigned_job_count: 0,
    placed_jobs: 0
  };

  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    return Promise.resolve({ data: { students: [student] } });
  });

  let eventSource;
  window.EventSource = function () {
    eventSource = this;
    this.close = jest.fn();
  };

  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );

  expect(await screen.findByText('a@example.com')).toBeInTheDocument();

  await act(async () => {
    eventSource.onmessage({ data: JSON.stringify(student) });
  });

  await waitFor(() => {
    expect(screen.getAllByText('a@example.com')).toHaveLength(1);
  });

  localStorage.clear();
  delete window.EventSource;
});
