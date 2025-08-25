import { render, screen, fireEvent, waitFor } from '@testing-library/react';
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

test('fetches licenses on load', async () => {
  const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYWRtaW4ifQ.signature';
  localStorage.setItem('token', token);
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  await waitFor(() => {
    expect(api.get).toHaveBeenCalledWith('/licenses');
  });
  localStorage.clear();
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
            student_id: '1',
            assigned_jobs: 0,
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
            student_id: '2',
            assigned_jobs: 0,
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
    if (url === '/students/all') {
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
              student_id: '1',
              assigned_jobs: 1,
              placed_jobs: 0
            }
          ]
        }
      });
    }
    if (url === '/students/1/assignments') {
      return Promise.resolve({
        data: {
          assigned_jobs: [
            {
              job_code: 'J1',
              job_title: 'Job 1',
              status: 'assigned',
              notes: [{ text: 'Test note' }]
            }
          ]
        }
      });
    }
    return Promise.resolve({ data: { students: [] } });
  });
  render(
    <BrowserRouter>
      <StudentProfiles />
    </BrowserRouter>
  );
  const expand = await screen.findByTitle('Expand');
  fireEvent.click(expand);
  const viewNotes = await screen.findByText(/View Notes/);
  fireEvent.click(viewNotes);
  expect(await screen.findByText('Test note')).toBeInTheDocument();
  fireEvent.click(screen.getByText('X'));
  await waitFor(() => {
    expect(screen.queryByText('Test note')).not.toBeInTheDocument();
  });
  localStorage.clear();
});
