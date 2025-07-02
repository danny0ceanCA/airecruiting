import { render } from '@testing-library/react';
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

test('renders StudentProfiles without errors', () => {
  api.get.mockResolvedValueOnce({ data: { students: [] } });
  expect(() => {
    render(
      <BrowserRouter>
        <StudentProfiles />
      </BrowserRouter>
    );
  }).not.toThrow();
});
