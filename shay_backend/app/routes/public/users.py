"""Additional-user creation for an existing company: POST /createUser."""

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.auth import get_password_hash
from app.models.user import User
from app.models.company import Company
from app.schemas.common import SuccessResponse

router = APIRouter()


@router.post("/createUser")
async def create_user(
    user_data: dict,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[dict]:
    """
    Create additional user for existing company.

    This endpoint allows companies to create additional users after initial setup.
    """
    try:
        email = user_data.get("email")
        password = user_data.get("password")
        company_id = user_data.get("companyId")

        if not email or not password or not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email, password, and company ID are required"
            )

        # Check if company exists
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        if not company_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company not found"
            )

        # Check if user already exists
        existing_user = await db.execute(
            select(User).where(User.email_id == email)
        )
        if existing_user.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )

        # Create user
        user_id = uuid.uuid4()
        hashed_password = get_password_hash(password)

        user = User(
            id=user_id,
            email_id=email,
            password_hash=hashed_password,
            company_id=company_id,
            role="customer",  # Default role for additional users
            is_active=True,
            created_datetime=datetime.utcnow(),
            updated_datetime=datetime.utcnow()
        )

        db.add(user)
        await db.commit()

        # Verify the user was created
        verify_user = await db.execute(
            select(User).where(User.id == user_id)
        )
        created_user = verify_user.scalar_one_or_none()

        if not created_user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )

        return SuccessResponse(
            success=True,
            data={
                "userId": str(created_user.id),
                "email": created_user.email_id,
                "role": created_user.role
            },
            message="User created successfully!",
            code=status.HTTP_201_CREATED
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create user: {str(e)}"
        )
