"""
Aggregate data for openassessment.
"""
import csv
import json
from submissions import api as sub_api
from openassessment.workflow.models import AssessmentWorkflow
from openassessment.assessment.models import Assessment, AssessmentFeedback


class CsvWriter(object):
    """
    Dump openassessment data to CSV files.
    """

    MODELS = [
        'assessment', 'assessment_part',
        'assessment_feedback', 'assessment_feedback_option',
        'submission', 'score'
    ]

    HEADERS = {
        'assessment': [
            'id', 'submission_uuid', 'scored_at',
            'scorer_id', 'score_type',
            'points_earned', 'points_possible', 'feedback',
        ],
        'assessment_part': [
            'assessment_id', 'points_earned',
            'criterion_name', 'option_name', 'feedback'
        ],
        'assessment_feedback': [
            'submission_uuid', 'feedback_text', 'options'
        ],
        'assessment_feedback_option': [
            'id', 'text'
        ],
        'submission': [
            'uuid', 'student_id', 'item_id',
            'submitted_at', 'created_at', 'raw_answer'
        ],
        'score': [
            'submission_uuid',
            'points_earned', 'points_possible',
            'created_at',
        ]
    }

    QUERY_INTERVAL = 100

    def __init__(self, output_streams, progress_callback=None):
        """
        Configure where the writer will write data.

        You can provide open file handles for each of the available
        models (see `AssessmentCsvWriter.MODELS`).  If you don't
        provide an output stream, the writer won't produce data
        for that model.

        Args:
            output_streams (dictionary): Provide the file handles
                to write CSV data to.

        Kwargs:
            progress_callback (callable): Callable that accepts
                no arguments.  Called once per submission loaded
                from the database.

        Example usage:
            >>> output_streams = {
            >>>     "submission": open('submissions.csv', 'w'),
            >>>     "score": open('scores.csv', 'w')
            >>> }
            >>> writer = AssessmentsCsvWriter(output_streams)
            >>> writer.write_to_csv()

        """
        self.writers = {
            key: csv.writer(file_handle)
            for key, file_handle in output_streams.iteritems()
            if key in self.MODELS
        }
        self._progress_callback = progress_callback

    def write_to_csv(self, course_id):
        """
        Write assessment and submission data for a course to CSV files.

        NOTE: The current implementation optimizes for memory usage,
        but not for the number of database queries.  All the queries
        use indexed fields (the submission uuid), so they should be
        relatively quick.

        Args:
            course_id (unicode): The course ID from which to pull data.

        Returns:
            None

        """
        self._write_csv_headers()

        for submission_uuid in self._submission_uuids(course_id):
            self._write_submission_to_csv(submission_uuid)

            for assessment in Assessment.objects.filter(submission_uuid=submission_uuid):
                self._write_assessment_to_csv(assessment)

            feedback_option_set = set()
            for assessment_feedback in AssessmentFeedback.objects.filter(submission_uuid=submission_uuid):
                self._write_assessment_feedback_to_csv(assessment_feedback)
                feedback_option_set.update(set(
                    option for option in assessment_feedback.options.all()
                ))
            self._write_feedback_options_to_csv(feedback_option_set)

            if self._progress_callback is not None:
                self._progress_callback()

    def _submission_uuids(self, course_id):
        """
        Iterate over submission uuids.
        Makes database calls every N submissions to avoid loading
        all submission uuids into memory at once.

        Args:
            course_id (unicode): The ID of the course to retrieve submissions from.

        Yields:
            submission_uuid (unicode)

        """
        num_results = 0
        start = 0
        total_results = AssessmentWorkflow.objects.filter(
            course_id=course_id
        ).count()

        while num_results < total_results:
            # Load a subset of the submission UUIDs
            # We're assuming that peer workflows are immutable,
            # so if we counted N at the start of the loop,
            # there should be >= N for us to process.
            end = start + self.QUERY_INTERVAL
            query = AssessmentWorkflow.objects.filter(
                course_id=course_id
            ).order_by('created').values('submission_uuid')[start:end]

            for workflow_dict in query:
                num_results += 1
                yield workflow_dict['submission_uuid']

            start += self.QUERY_INTERVAL

    def _write_csv_headers(self):
        """
        Write the headers (first row) for each output stream.
        """
        for name, writer in self.writers.iteritems():
            writer.writerow(self.HEADERS[name])

    def _write_submission_to_csv(self, submission_uuid):
        """
        Write submission data to CSV.

        Args:
            submission_uuid (unicode): The UUID of the submission to write.

        Returns:
            None

        """
        submission = sub_api.get_submission_and_student(submission_uuid)
        self._write_unicode('submission', [
            submission['uuid'],
            submission['student_item']['student_id'],
            submission['student_item']['item_id'],
            submission['submitted_at'],
            submission['created_at'],
            json.dumps(submission['answer'])
        ])

        score = sub_api.get_latest_score_for_submission(submission_uuid)
        if score is not None:
            self._write_unicode('score', [
                score['submission_uuid'],
                score['points_earned'],
                score['points_possible'],
                score['created_at']
            ])

    def _write_assessment_to_csv(self, assessment):
        """
        Write assessments and assessment parts to CSV.

        Args:
            assessment (Assessment): The assessment model to write.

        Returns:
            None

        """
        self._write_unicode('assessment', [
            assessment.id,
            assessment.submission_uuid,
            assessment.scored_at,
            assessment.scorer_id,
            assessment.score_type,
            assessment.points_earned,
            assessment.points_possible,
            assessment.feedback
        ])

        for part in assessment.parts.all():
            self._write_unicode('assessment_part', [
                assessment.id,
                part.option.points,
                part.option.criterion.name,
                part.option.name,
                part.feedback
            ])

    def _write_assessment_feedback_to_csv(self, assessment_feedback):
        """
        Write feedback on assessments to CSV.

        Args:
            assessment_feedback (AssessmentFeedback): The feedback model to write.

        Returns:
            None

        """
        options_string = ",".join([
            unicode(option.id) for option in assessment_feedback.options.all()
        ])

        self._write_unicode('assessment_feedback', [
            assessment_feedback.submission_uuid,
            assessment_feedback.feedback_text,
            options_string
        ])

    def _write_feedback_options_to_csv(self, feedback_options):
        """
        Write feedback on assessment options to CSV.

        Args:
            feedback_options (iterable of AssessmentFeedbackOption)

        Returns:
            None

        """
        for option in feedback_options:
            self._write_unicode(
                'assessment_feedback_option',
                [option.id, option.text]
            )

    def _write_unicode(self, output_name, row):
        """
        Encode a row as a UTF-8 bytestring, then write it to a CSV file.
        Non-string values are first converted to unicode.

        Args:
            output_name (str): The name of the output stream to write to.
            row (list): List of fields, which must be serializable as UTF-8.

        Returns:
            None

        """
        writer = self.writers.get(output_name)
        if writer is not None:
            encoded_row = [unicode(field).encode('utf-8') for field in row]
            writer.writerow(encoded_row)
