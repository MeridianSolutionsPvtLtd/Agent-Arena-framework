"""
Prompt templates for Call Audit Agent.
"""
from datetime import date


def get_analysis_prompt(transcript_text: str, segment_context: str) -> str:
    """Build the full analysis prompt with today's date injected."""
    today_date = date.today().strftime("%Y-%m-%d")

    prompt = f"""Today is {today_date}. Please analyze the following transcript of an enterprise call audit.

IMPORTANT LANGUAGE NOTE:

The transcript below may be in English, Hindi, or Hinglish (Hindi written in English script).
Your task is to extract structured insights in JSON format for the Organization, focusing on call quality, participant eligibility, service information, and adherence to audit parameters.

### Service Eligibility Criteria:
The organization offers multiple services with specific requirements. Participants are evaluated based on:

1. **Standard Packages**
   - General Age requirement: 18 to 28 years
   - Educational prerequisites: High School or Graduate
   - Interest level: Professional or Student

### ENHANCED ELIGIBILITY EXTRACTION RULES:
CRITICAL: You MUST extract ALL eligibility information from the transcript:

1. **Date of Birth (DOB) Extraction:**
   - Look for explicit mentions: "date of birth", "DOB", "janam tithi", "umar", "age"
   - Extract from context: "I was born in 1998", "meri janam tithi 15 June 2005 hai"
   - Handle Hindi/English mixed formats
   - Convert all formats to YYYY-MM-DD

2. **Qualification Extraction:**
   - Look for: "graduation", "12th", "intermediate", "degree", "qualification"
   - Hindi equivalents: "grEjuET", "bA. a.", "pA. a.", "iglyAj meM", "kakshA bArahvIM"
   - Extract stream if mentioned

3. **Age Calculation:**
   - Calculate age based on DOB and today's date ({today_date})
   - If only year provided, calculate approximate age
   - Determine eligibility based on general requirements

4. **ELIGIBILITY:**
   - If there is a slot booked, a service confirmed, or the agent says that the user is eligible, mark as eligible

### CALL COMPLETION STATUS DETECTION:
Analyze whether the call was properly completed or disconnected.

**Determine Call_Status based on:**
- "Call_Disconnected": True if call ended abruptly
- "Call_Completion_Status": True if conversation reached natural conclusion

### LANGUAGE PROCESSING GUIDELINES:
1. Handle mixed English-Hindi content
2. Understand common Hindi words in English script
3. Look for context and approximate matches for speech recognition errors
4. Focus on key information: Names, numbers, dates, service discussions

### ENHANCED PHONE NUMBER EXTRACTION RULES:
1. Company Fixed Number: 18002587332
2. Extract ALL phone number discussions
3. Validate Indian mobile numbers (start with 6,7,8,9 + 10 digits)
4. If no valid phone numbers found, use "not provided"

### NAME EXTRACTION GUIDELINES:
#### Agent Name:
- Look for intro patterns: "This is [Name] from the Company", "My name is [Name]"
- Extract in Hindi also
- If not found: "not provided"

#### Student Name:
- Look for self-introductions or agent references
- If not found: "not provided"

### AUDIO MARKERS TO EXTRACT:
greeting, qualification_check, eligibility_check, service_invitation, slot_confirmation,
location_check, document_verification, follow_up, parents_confirmation, service_information,
pricing_discussion, professional_guidance, objection_handling, closing, contact_sharing

### COMPREHENSIVE AUDIT PARAMETERS (32 Parameters):
1. Eligibility Check - DOB (Yes/No)
2. Eligibility Check - Qualification/Stream (Yes/No)
3. Was User eligible (Yes/No/NA)
4. Service info shared/Duration informed (Yes/No/NA)
5. Incorrect & Incomplete Info not shared (Yes/No)
6. Data Manipulation not done (Yes/No)
7. Fake Appointment - 100% Confirmation missing (Yes/No/NA)
8. No Rude and abusive behaviour (Yes/No)
9. Opening in English (Yes/No)
10. Greeting (Yes/No)
11. Self Introduction & Branding (Yes/No)
12. Call Flow adherence (Yes/No)
13. Closing/Further Assistance (Yes/No/NA)
14. Reason Of Call - Presentation/Seminar (Yes/No)
15. Reason Of Call - Industry info (Yes/No)
16. Reason Of Call - Benefit demonstration (Yes/No/NA)
17. Stakeholder's invitation (Yes/No/NA)
18. Value/Need creation (Yes/No/NA)
19. Importance of Opportunity/Time Pitched (Yes/No/NA)
20. Right Probing done (Yes/No)
21. Rebuttals/Correct Objection Handling (Yes/No/NA)
22. 100% affirmation/consent for next step (Yes/No/NA)
23. No irrelevant information (Yes/No)
24. Tagging/Disposition (Yes/No)
25. Appointment/Address provided (Yes/No/NA)
26. Rate of Speech (Good/Poor)
27. Correct Energy Level (High/Medium/Low)
28. No Fumbling/No Fillers (Yes/No)
29. No MTI & No Pronunciation/Grammatical Errors (Yes/No)
30. Attentiveness/Active Listening (Yes/No)
31. Politeness/No Casual Approach/No Sarcasm (Yes/No)
32. Language Adherence/No Auto Switching (Yes/No)

### Final JSON structure (respond ONLY with valid JSON, no markdown):
{{
    "Call_Metadata": {{
        "Agent_Name": "not provided",
        "Date_of_Call": "{today_date}",
        "Student_Name": "not provided",
        "Phone_Numbers": [
            {{
                "number": "10-digit valid number OR 'partial' OR 'discussed' OR 'not provided'",
                "context": "How this number was mentioned",
                "extracted_from": "Exact text segment"
            }}
        ],
        "Phone_Number_Discussions": [
            {{
                "segment": "Exact transcript portion",
                "context": "What was being discussed",
                "outcome": "number_shared/number_requested/company_number_shared/promised_to_share"
            }}
        ],
        "Call_Purpose": "Primary objective",
        "Next_Plan": "Next step decided"
    }},
    "Eligibility": {{
        "DOB": "YYYY-MM-DD or not provided",
        "DOB_Original": "Original format from transcript",
        "Qualification_Stream": "not provided",
        "Was_Student_Eligible": "Yes/No",
        "Eligibility_Details": "Which courses eligible for"
    }},
    "Student_Course_Info": {{
        "Area_of_Interest": "not provided",
        "Courses_Offered": ["List from 6 fixed courses"],
        "Course_Discussed": "Specific course"
    }},
    "Disposition": {{
        "Agent_Disposition": "not provided",
        "Correct_Disposition_Tagged_By_Agent": "Yes/No"
    }},
    "Audit_Parameters": {{
        "Eligibility_Check_DOB": "Yes/No",
        "Eligibility_Check_Qualification": "Yes/No",
        "Student_Eligible": "Yes/No/NA",
        "Course_Info_Shared": "Yes/No/NA",
        "Incorrect_Incomplete_Info_Shared": "Yes/No",
        "Job_Data_Manipulation": "Yes/No",
        "Fake_Appointment": "Yes/No/NA",
        "Rude_Abusive_Behavior": "Yes/No",
        "Opening_in_English": "Yes/No",
        "Greeting": "Yes/No",
        "Self_Introduction_Branding": "Yes/No",
        "Call_Flow_Adherence": "Yes/No",
        "Closing_Further_Assistance": "Yes/No/NA",
        "Reason_Free_Counseling_Seminar": "Yes/No",
        "Reason_Industry_Info": "Yes/No",
        "Reason_Highest_Salary": "Yes/No/NA",
        "Parent_Invitation": "Yes/No/NA",
        "Scholarship_Need_Creation": "Yes/No/NA",
        "Seat_Importance_Pitched": "Yes/No/NA",
        "Right_Probing": "Yes/No",
        "Rebuttals_Objection_Handling": "Yes/No/NA",
        "Consent_for_Seminar": "Yes/No/NA",
        "No_Irrelevant_Info": "Yes/No",
        "Tagging_Disposition": "Yes/No",
        "Appointment_Center_Address_Provided": "Yes/No/NA",
        "Rate_of_Speech": "Good/Poor",
        "Energy_Level": "High/Medium/Low",
        "Fumbling_Fillers": "Yes/No",
        "MTI_Grammar_Errors": "Yes/No",
        "Active_Listening": "Yes/No",
        "Politeness": "Yes/No",
        "Language_Adherence": "Yes/No"
    }},
    "Scores": {{
        "Professionalism": 0,    // Score from 1 to 10
        "Product_Knowledge": 0,  // Score from 1 to 10
        "Communication_Skills": 0, // Score from 1 to 10
        "Problem_Solving": 0,    // Score from 1 to 10
        "TotalScore": 0,         // Sum of the four categories above (max 40)
        "Category": "Excellent/Average/Poor"
    }},
    "Escalation": {{
        "Escalation_Received_From": "not provided",
        "Closed_Pending": "Closed/Pending",
        "Week": "not provided",
        "Month": "not provided"
    }},
    "Additional_Observations": {{
        "Area_of_Improvement": "not provided",
        "Other_Observation": "not provided",
        "Probing_for_Staying_with_Parents": "Yes/No/Not Provided",
        "Staying_with_Parents": "Yes/No/Not Provided"
    }},
    "Follow_Up": {{
        "Follow_Up_or_Callback_Date": "YYYY-MM-DD or not provided",
        "Purpose_of_Follow_Up": "not provided"
    }},
    "Call_Status": {{
        "Call_Disconnected": "True/False",
        "Call_Completion_Status": "True/False"
    }},
    "Call_Summary": {{
        "Summary_Bullet_Points": [
            "• Key point 1",
            "• Key point 2"
        ]
    }},
    "Audio_Markers": [
        {{
            "time": "HH:MM:SS",
            "label": "Descriptive label",
            "type": "greeting/qualification_check/eligibility_check/etc.",
            "transcript_segment": "Exact text from transcript"
        }}
    ]
}}

### Transcript Segments:
{segment_context}

Transcript for analysis:
{transcript_text}
"""
    return prompt
