import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { act } from 'react';
import StudentProfiles from './StudentProfiles';
import { BrowserRouter } from 'react-router-dom';
import api from './api';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    create: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    }
  };
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
    if (url.includes('/job-stats')) {
      return Promise.resolve({
        data: { assigned: [], placed: [], rejected: [], uninterested: [] }
      });
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
            license: ''
          },
          {
            first_name: 'C',
            last_name: 'D',
            email: 'c@example.com',
            city: 'City',
            state: 'ST',
            institutional_code: 'ABC',
            license: ''
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

test('loads job analytics when tab selected', async () => {
  const token =
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiY2FyZWVyIiwic3ViIjoiY2FyZWVyQGV4YW1wbGUuY29tIn0.signature';
  localStorage.setItem('token', token);
  api.get.mockImplementation((url, options) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    if (url === '/students/by-school') {
      return Promise.resolve({ data: { students: [] } });
    }
    if (url === '/job-analytics') {
      expect(options).toEqual({
        headers: { Authorization: `Bearer ${token}` },
      });
      return Promise.resolve({
        data: {
          jobs: [
            {
              job_code: 'J1',
              job_title: 'Job One',
              source: 'Campus',
              timestamp: '2024-01-01T00:00:00',
              assigned_count: 2,
              placed_count: 1,
              rejected_count: 0,
              uninterested_count: 1,
              email_sent_count: 2,
              opened_count: 1,
              clicked_count: 1,
              students: [
                {
                  email: 'student@example.com',
                  first_name: 'Stu',
                  last_name: 'Dent',
                  status: 'assigned',
                  email_sent: '2024-01-01T00:00:00',
                  first_open: '2024-01-01T12:00:00',
                  clicked: false,
                },
              ],
            },
          ],
        },
      });
    }
    throw new Error(`Unexpected URL ${url}`);
  });

  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );

  fireEvent.click(await screen.findByText('Job Analytics'));

  expect(await screen.findByText('Job One')).toBeInTheDocument();

  const expand = await screen.findByTitle('Expand');
  fireEvent.click(expand);
  expect(screen.getByText('Stu Dent')).toBeInTheDocument();
  expect(screen.getByText('student@example.com')).toBeInTheDocument();
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
    if (url === '/students/s@example.com/job-stats') {
      return Promise.resolve({
        data: { assigned: ['J1'], placed: [], rejected: [], uninterested: [] }
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
            institutional_code: 'ABC'
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
    if (url === '/students/s@example.com/job-stats') {
      return Promise.resolve({
        data: { assigned: ['J1'], placed: [], rejected: [], uninterested: [] }
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
            institutional_code: 'ABC'
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

test('shows placement controls after job stats load', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiY2FyZWVyX3N0YWZmIn0.signature';
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
    if (url === '/students/s@example.com/job-stats') {
      return Promise.resolve({
        data: { assigned: ['J1'], placed: [], rejected: [], uninterested: [] }
      });
    }
    if (url === '/students/by-school') {
      return Promise.resolve({
        data: {
          students: [
            {
              first_name: 'F',
              last_name: 'L',
              email: 's@example.com',
              city: 'City',
              state: 'ST',
              institutional_code: 'ABC'
            }
          ]
        }
      });
    }
    return Promise.resolve({ data: {} });
  });
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  const expand = await screen.findByTitle('Expand');
  fireEvent.click(expand);
  expect(await screen.findByText('Mark as Placed')).toBeInTheDocument();
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
    license: ''
  };

  api.get.mockImplementation((url) => {
    if (url === '/licenses') {
      return Promise.resolve({ data: { licenses: [] } });
    }
    if (url.includes('/job-stats')) {
      return Promise.resolve({
        data: { assigned: [], placed: [], rejected: [], uninterested: [] }
      });
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
