import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import './App.css';
import LoginForm from './LoginForm';
import RegisterForm from './RegisterForm';
import Dashboard from './Dashboard';
import ProtectedRoute from './ProtectedRoute';
import AdminPending from './AdminPending';
import StudentProfiles from './StudentProfiles';
import ApplicantProfile from './ApplicantProfile';
import JobPosting from './JobPosting';
import Metrics from './Metrics';
import CareerStaffInfo from './CareerStaffInfo';
import ActivityLog from './ActivityLog';
import AdminUsers from './AdminUsers';

function App() {
  return (
    <Router>
      <div className="App">
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginForm />} />
          <Route path="/register" element={<RegisterForm />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/students"
            element={
              <ProtectedRoute>
                <StudentProfiles />
              </ProtectedRoute>
            }
          />
          <Route
            path="/applicant/profile"
            element={
              <ProtectedRoute>
                <ApplicantProfile />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/pending"
            element={
              <ProtectedRoute>
                <AdminPending />
              </ProtectedRoute>
            }
          />
            <Route
              path="/admin/jobs"
              element={
                <ProtectedRoute>
                  <JobPosting />
                </ProtectedRoute>
              }
            />
          <Route
            path="/admin/activity-log"
            element={
              <ProtectedRoute>
                <ActivityLog />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute>
                <AdminUsers />
              </ProtectedRoute>
            }
          />
          <Route
            path="/recruiter/jobs"
            element={
              <ProtectedRoute>
                <JobPosting />
                </ProtectedRoute>
              }
            />
          <Route
            path="/metrics"
            element={
              <ProtectedRoute>
                <Metrics />
              </ProtectedRoute>
            }
          />
          <Route
            path="/career-info"
            element={
              <ProtectedRoute>
                <CareerStaffInfo />
              </ProtectedRoute>
            }
          />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
